from __future__ import annotations
from pathlib import Path
import os
from dotenv import load_dotenv

from typing import Any, Dict, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

ENV_PATH = Path(__file__).resolve().parents[1] / ".env" # backend/
load_dotenv(dotenv_path=ENV_PATH, override=True)

from app.dashboard import router as dashboard_router

app = FastAPI(title="VALORANT Assistant Coach API")

app.include_router(dashboard_router)

DATA_DIR = Path(os.getenv("DATA_DIR", "/root/code/code_projects/valor-rant/data"))
DOCS_DIR = Path(os.getenv("DOCS_DIR", "/root/code/code_projects/valor-rant/docs"))


BASE_DIR = Path(__file__).resolve().parent  # backend/app
STATIC_DIR = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")




@app.get("/debug/env")
def debug_env():
    return {"has_openai_key": bool(os.getenv("OPENAI_API_KEY"))}

@app.get("/health")
def health():
    return {"status": "ok"}


def load_csv(name: str) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Missing {path}")
    try:
        return pd.read_csv(path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read {name}: {e}")


def filter_rounds(
    rounds: pd.DataFrame,
    map: Optional[str],
    side: Optional[str],
    site: Optional[str],
) -> pd.DataFrame:
    r = rounds.copy()

    # side/site live in rounds.csv
    if side:
        if "side" not in r.columns:
            raise HTTPException(status_code=400, detail="rounds.csv missing 'side' column (required for side filter).")
        r = r[r["side"].astype(str).str.upper() == str(side).upper()]

    if site:
        if "site_hit" not in r.columns:
            raise HTTPException(status_code=400, detail="rounds.csv missing 'site_hit' column (required for site filter).")
        r = r[r["site_hit"].astype(str).str.upper() == str(site).upper()]

    # map lives in matches.csv, filter rounds by match_id where matches.map == map
    if map:
        matches = load_csv("matches.csv").copy()
        if "map" not in matches.columns:
            raise HTTPException(status_code=400, detail="matches.csv missing 'map' column (required for map filter).")
        match_ids = matches[matches["map"].astype(str).str.lower() == str(map).lower()]["match_id"].tolist()
        r = r[r["match_id"].isin(match_ids)]

    return r

@app.get("/meta/ai")
def meta_ai():
    return {"ai_enabled": bool(os.getenv("OPENAI_API_KEY"))}


@app.get("/meta/options")
def meta_options():
    matches = load_csv("matches.csv").copy()
    rounds = load_csv("rounds.csv").copy()

    maps = sorted([m for m in matches["map"].dropna().astype(str).unique().tolist() if m]) if "map" in matches.columns else []
    sides = sorted([s for s in rounds["side"].dropna().astype(str).unique().tolist() if s]) if "side" in rounds.columns else []
    sites = sorted([s for s in rounds["site_hit"].dropna().astype(str).unique().tolist() if s]) if "site_hit" in rounds.columns else []

    return {"maps": maps, "sides": sides, "sites": sites}


@app.get("/data/summary")
def data_summary():
    matches = load_csv("matches.csv")
    players = load_csv("players.csv")
    rounds = load_csv("rounds.csv")
    return {
        "data_dir": str(DATA_DIR),
        "matches": {"rows": len(matches), "cols": list(matches.columns)},
        "players": {"rows": len(players), "cols": list(players.columns)},
        "rounds": {"rows": len(rounds), "cols": list(rounds.columns)},
    }


@app.get("/insights/first-deaths")
def first_deaths_insights(
    min_fd: int = 2,
    map: Optional[str] = None,
    side: Optional[str] = None,
    site: Optional[str] = None,
):
    rounds = load_csv("rounds.csv")
    rounds = filter_rounds(rounds, map=map, side=side, site=site)

    required_cols = {"match_id", "round_number", "won", "first_death_player", "first_death_role"}
    missing = required_cols - set(rounds.columns)
    if missing:
        raise HTTPException(status_code=400, detail=f"rounds.csv missing columns: {sorted(missing)}")

    rounds = rounds.copy()
    rounds["won"] = pd.to_numeric(rounds["won"], errors="coerce")
    rounds["round_number"] = pd.to_numeric(rounds["round_number"], errors="coerce")
    rounds["first_death_player"] = rounds["first_death_player"].fillna("").astype(str).str.strip()
    rounds["first_death_role"] = rounds["first_death_role"].fillna("").astype(str).str.strip()

    if rounds["won"].dropna().max() > 1:
        raise HTTPException(status_code=400, detail="'won' must be 0/1. Check rounds.csv.")

    total_rounds = int(len(rounds))
    baseline_win_rate = float(rounds["won"].mean()) if total_rounds else 0.0

    fd_rows = rounds[rounds["first_death_player"] != ""].copy()

    grp = fd_rows.groupby("first_death_player", as_index=False).agg(
        first_deaths=("first_death_player", "count"),
        win_rate_when_fd=("won", "mean"),
    )

    grp["fd_rate"] = grp["first_deaths"] / max(total_rounds, 1)
    grp["impact_delta"] = grp["win_rate_when_fd"] - baseline_win_rate

    role_mode = (
        fd_rows.groupby("first_death_player")["first_death_role"]
        .agg(lambda s: s.mode().iloc[0] if not s.mode().empty else "")
        .reset_index()
        .rename(columns={"first_death_role": "most_common_fd_role"})
    )
    grp = grp.merge(role_mode, on="first_death_player", how="left")

    grp = grp[grp["first_deaths"] >= int(min_fd)].copy()
    grp.sort_values(by=["impact_delta", "first_deaths"], ascending=[True, False], inplace=True)

    def pct(x: float) -> float:
        return round(float(x) * 100, 1)

    results = []
    for _, r in grp.iterrows():
        results.append(
            {
                "player": r["first_death_player"],
                "most_common_fd_role": r.get("most_common_fd_role", ""),
                "first_deaths": int(r["first_deaths"]),
                "fd_rate_pct": pct(r["fd_rate"]),
                "round_win_pct_when_fd": pct(r["win_rate_when_fd"]),
                "baseline_round_win_pct": pct(baseline_win_rate),
                "impact_delta_pct_points": round(pct(r["win_rate_when_fd"]) - pct(baseline_win_rate), 1),
            }
        )

    return {
        "filters": {"map": map, "side": side, "site": site},
        "total_rounds": total_rounds,
        "baseline_round_win_pct": pct(baseline_win_rate),
        "min_fd_filter": int(min_fd),
        "players": results,
        "notes": [
            "impact_delta_pct_points is (win% when player is first death) - (baseline win%).",
            "More negative impact means that player's first deaths correlate with more lost rounds.",
        ],
    }


@app.get("/insights/trades")
def trade_insights(
    min_fd: int = 2,
    map: Optional[str] = None,
    side: Optional[str] = None,
    site: Optional[str] = None,
):
    rounds = load_csv("rounds.csv").copy()
    rounds = filter_rounds(rounds, map=map, side=side, site=site)

    required_cols = {
        "match_id",
        "round_number",
        "won",
        "first_death_player",
        "first_death_role",
        "traded_within_5s",
    }
    missing = required_cols - set(rounds.columns)
    if missing:
        raise HTTPException(status_code=400, detail=f"rounds.csv missing columns: {sorted(missing)}")

    rounds["won"] = pd.to_numeric(rounds["won"], errors="coerce")
    rounds["round_number"] = pd.to_numeric(rounds["round_number"], errors="coerce")
    rounds["traded_within_5s"] = pd.to_numeric(rounds["traded_within_5s"], errors="coerce")
    rounds["first_death_player"] = rounds["first_death_player"].fillna("").astype(str).str.strip()
    rounds["first_death_role"] = rounds["first_death_role"].fillna("").astype(str).str.strip()

    if rounds["won"].dropna().max() > 1:
        raise HTTPException(status_code=400, detail="'won' must be 0/1. Check rounds.csv.")
    if rounds["traded_within_5s"].dropna().max() > 1:
        raise HTTPException(status_code=400, detail="'traded_within_5s' must be 0/1. Check rounds.csv.")

    total_rounds = int(len(rounds))
    baseline_win_rate = float(rounds["won"].mean()) if total_rounds else 0.0

    fd = rounds[rounds["first_death_player"] != ""].copy()
    if len(fd) == 0:
        return {
            "filters": {"map": map, "side": side, "site": site},
            "total_rounds": total_rounds,
            "baseline_round_win_pct": round(baseline_win_rate * 100, 1),
            "message": "No first-death rows found.",
        }

    traded = fd[fd["traded_within_5s"] == 1]
    untraded = fd[fd["traded_within_5s"] == 0]

    team_trade_stats = {
        "first_death_events": int(len(fd)),
        "traded_first_deaths": int(len(traded)),
        "untraded_first_deaths": int(len(untraded)),
        "trade_rate_pct": round((len(traded) / max(len(fd), 1)) * 100, 1),
        "win_pct_when_traded_fd": round(float(traded["won"].mean()) * 100, 1) if len(traded) else None,
        "win_pct_when_untraded_fd": round(float(untraded["won"].mean()) * 100, 1) if len(untraded) else None,
        "baseline_round_win_pct": round(baseline_win_rate * 100, 1),
    }

    grp = fd.groupby("first_death_player", as_index=False).agg(
        first_deaths=("first_death_player", "count"),
        trade_rate=("traded_within_5s", "mean"),
        win_rate_when_fd=("won", "mean"),
    )
    grp["untraded_fd"] = grp["first_deaths"] - (grp["trade_rate"] * grp["first_deaths"])
    grp["impact_delta"] = grp["win_rate_when_fd"] - baseline_win_rate

    role_mode = (
        fd.groupby("first_death_player")["first_death_role"]
        .agg(lambda s: s.mode().iloc[0] if not s.mode().empty else "")
        .reset_index()
        .rename(columns={"first_death_role": "most_common_fd_role"})
    )
    grp = grp.merge(role_mode, on="first_death_player", how="left")

    grp = grp[grp["first_deaths"] >= int(min_fd)].copy()
    grp.sort_values(by=["trade_rate", "first_deaths"], ascending=[True, False], inplace=True)

    def pct(x: float) -> float:
        return round(float(x) * 100, 1)

    players = []
    for _, r in grp.iterrows():
        players.append(
            {
                "player": r["first_death_player"],
                "most_common_fd_role": r.get("most_common_fd_role", ""),
                "first_deaths": int(r["first_deaths"]),
                "trade_rate_pct": pct(r["trade_rate"]),
                "estimated_untraded_fd": int(round(float(r["untraded_fd"]))),
                "round_win_pct_when_fd": pct(r["win_rate_when_fd"]),
                "impact_delta_pct_points": round(pct(r["win_rate_when_fd"]) - pct(baseline_win_rate), 1),
            }
        )

    role_grp = fd.groupby("first_death_role", as_index=False).agg(
        first_deaths=("first_death_role", "count"),
        trade_rate=("traded_within_5s", "mean"),
        win_rate=("won", "mean"),
    )
    role_grp.sort_values(by=["trade_rate", "first_deaths"], ascending=[True, False], inplace=True)

    roles = []
    for _, r in role_grp.iterrows():
        roles.append(
            {
                "role": r["first_death_role"],
                "first_deaths": int(r["first_deaths"]),
                "trade_rate_pct": pct(r["trade_rate"]),
                "round_win_pct": pct(r["win_rate"]),
            }
        )

    return {
        "filters": {"map": map, "side": side, "site": site},
        "total_rounds": total_rounds,
        "baseline_round_win_pct": round(baseline_win_rate * 100, 1),
        "team_trade_summary": team_trade_stats,
        "players": players,
        "roles": roles,
        "notes": [
            "Trade rate is computed only on rounds where a first death is recorded.",
            "Low trade_rate_pct suggests spacing/coordination issues (or isolated deaths).",
            "win_pct_when_untraded_fd is usually much lower than baseline—this is a key coaching lever.",
        ],
    }


def _rule_based_coach_report(fd_json: Dict[str, Any], trades_json: Dict[str, Any]) -> str:
    baseline = fd_json.get("baseline_round_win_pct")
    players_fd = fd_json.get("players", [])
    team_trade = trades_json.get("team_trade_summary", {})
    roles = trades_json.get("roles", [])
    players_trades = trades_json.get("players", [])

    worst = None
    if players_fd:
        worst = sorted(players_fd, key=lambda x: x.get("impact_delta_pct_points", 0))[0]

    worst_role = None
    if roles:
        worst_role = sorted(roles, key=lambda x: x.get("trade_rate_pct", 100))[0]

    traded_win = team_trade.get("win_pct_when_traded_fd")
    untraded_win = team_trade.get("win_pct_when_untraded_fd")
    trade_rate = team_trade.get("trade_rate_pct")

    lines = []
    lines.append("COACH BRIEFING — VALORANT ASSISTANT COACH (Prototype)")
    lines.append("")
    lines.append(f"Team baseline round win rate: {baseline}%")
    lines.append("")
    lines.append("1) The single biggest lever")
    lines.append(f"- First-death trade rate: {trade_rate}%")
    lines.append(f"- Win% when first death is TRADED: {traded_win}%")
    lines.append(f"- Win% when first death is UNTRADED: {untraded_win}%")
    lines.append("➡️ Coaching takeaway: Treat every early duel as a *pair* — trade discipline is non-negotiable.")
    lines.append("")

    if worst:
        lines.append("2) Player focus (highest negative impact)")
        lines.append(
            f"- {worst['player']} ({worst.get('most_common_fd_role','')}): "
            f"{worst['first_deaths']} first deaths ({worst['fd_rate_pct']}% of rounds), "
            f"round win% when FD = {worst['round_win_pct_when_fd']}% "
            f"(impact {worst['impact_delta_pct_points']}pp vs baseline)"
        )

        trow = next((p for p in players_trades if p["player"] == worst["player"]), None)
        if trow:
            lines.append(
                f"- Trade discipline: {trow['trade_rate_pct']}% traded; "
                f"estimated untraded first deaths: {trow['estimated_untraded_fd']}"
            )
        lines.append("➡️ Coaching actions:")
        lines.append("- Shift entry timings to utility-first clears (flash/drone/dog), reduce dry peeks.")
        lines.append("- Enforce 2-man spacing on first contact (trade within 1–2 steps).")
        lines.append("- If entry must take solo space: use contact bait setups, not isolated swings.")
        lines.append("")

    if worst_role:
        lines.append("3) Role-level diagnosis")
        lines.append(
            f"- Weakest role trade discipline: {worst_role['role']} "
            f"(trade rate {worst_role['trade_rate_pct']}%, win% {worst_role['round_win_pct']}%)"
        )
        lines.append("➡️ Coaching actions:")
        lines.append("- Tighten default spacing for that role; pair with initiator utility windows.")
        lines.append("- Add a simple rule: 'no first fight without trade angle established.'")
        lines.append("")

    lines.append("4) Practice plan (30–45 min block)")
    lines.append("- 10 min: 2v2 trade drills (swing on contact, no hesitation).")
    lines.append("- 15 min: execute reps on A/B with strict trade spacing.")
    lines.append("- 10 min: review first-death rounds, label: 'traded' vs 'untraded' and why.")
    lines.append("- 10 min: lock one adjustment for next scrim (timing/utility/spacing).")

    return "\n".join(lines)


@app.get("/report/coach")
def coach_report(
    model: str = "gpt-4o-mini",
    format: str = "text",
    map: Optional[str] = None,
    side: Optional[str] = None,
    site: Optional[str] = None,
):
    fd = first_deaths_insights(min_fd=2, map=map, side=side, site=site)
    trades = trade_insights(min_fd=2, map=map, side=side, site=site)
    fallback = _rule_based_coach_report(fd, trades)

    def to_markdown(text: str) -> str:
        md = text
        md = md.replace(
            "COACH BRIEFING — VALORANT ASSISTANT COACH (Prototype)",
            "# Coach Briefing — VALORANT Assistant Coach (Prototype)",
        )
        md = md.replace("\n\n1) ", "\n\n## 1) ").replace("\n\n2) ", "\n\n## 2) ").replace("\n\n3) ", "\n\n## 3) ").replace("\n\n4) ", "\n\n## 4) ")
        return md

    report_text = fallback if format.lower() != "markdown" else to_markdown(fallback)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "mode": "rule_based",
            "filters": {"map": map, "side": side, "site": site},
            "report": report_text,
            "note": "Set OPENAI_API_KEY to enable AI-written report.",
        }

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        prompt = f"""
You are an esports assistant coach for VALORANT. Write a concise coach briefing with actionable fixes.
Use the provided analytics JSON. Be specific and practical.
Structure:
- Key finding (1–2 bullets)
- Player focus (2–4 bullets)
- Team focus (2–4 bullets)
- 30-minute practice plan (bullets)

Filters:
MAP={map} SIDE={side} SITE={site}

Analytics:
FIRST_DEATHS={fd}
TRADES={trades}
""".strip()

        resp = client.responses.create(model=model, input=prompt, temperature=0.4)

        text = ""
        for item in getattr(resp, "output", []):
            if hasattr(item, "content"):
                for c in item.content:
                    if getattr(c, "type", "") == "output_text":
                        text += c.text

        text = (text.strip() or fallback)
        if format.lower() == "markdown":
            text = to_markdown(text)

        return {"mode": "ai", "model": model, "filters": {"map": map, "side": side, "site": site}, "report": text}

    except Exception as e:
        return {"mode": "rule_based_fallback", "filters": {"map": map, "side": side, "site": site}, "report": report_text, "error": str(e)}


@app.get("/report/coach/download")
def download_coach_report():
    fd = first_deaths_insights(min_fd=2)
    trades = trade_insights(min_fd=2)
    report = _rule_based_coach_report(fd, trades)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DOCS_DIR / "coach_report.md"

    md = (
        "# Coach Briefing — VALORANT Assistant Coach (Prototype)\n\n"
        + report.replace("COACH BRIEFING — VALORANT ASSISTANT COACH (Prototype)\n\n", "")
    )
    out_path.write_text(md, encoding="utf-8")

    return {
        "saved_to": str(out_path),
        "message": "Coach report saved. Commit docs/coach_report.md to your repo.",
        "docs_dir": str(DOCS_DIR),
    }

@app.get("/insights/round-autopsy")
def round_autopsy(
    map: Optional[str] = None,
    side: Optional[str] = None,
    site: Optional[str] = None,
    limit_examples: int = 8,
):
    """
    Labels each LOST round with a primary cause (v1 heuristic).
    Returns top causes + example rounds for coaching review.

    Causes (v1):
    - Untraded First Death (auto-loss indicator)
    - Dry Peek / No Utility (utility_used_before_first_death == 0)
    - Traded First Death But Still Lost (mid-round / exec issue)
    - No First-Death Logged (data gap or late-round collapse)
    """
    rounds = load_csv("rounds.csv").copy()
    rounds = filter_rounds(rounds, map=map, side=side, site=site) if "filter_rounds" in globals() else rounds

    required_cols = {
        "match_id", "round_number", "won",
        "side", "site_hit",
        "first_death_player", "first_death_role",
        "traded_within_5s", "utility_used_before_first_death"
    }
    missing = required_cols - set(rounds.columns)
    if missing:
        raise HTTPException(status_code=400, detail=f"rounds.csv missing columns: {sorted(missing)}")

    # Clean + coerce
    rounds["won"] = pd.to_numeric(rounds["won"], errors="coerce")
    rounds["round_number"] = pd.to_numeric(rounds["round_number"], errors="coerce")
    rounds["traded_within_5s"] = pd.to_numeric(rounds["traded_within_5s"], errors="coerce")
    rounds["utility_used_before_first_death"] = pd.to_numeric(rounds["utility_used_before_first_death"], errors="coerce")

    rounds["first_death_player"] = rounds["first_death_player"].fillna("").astype(str).str.strip()
    rounds["first_death_role"] = rounds["first_death_role"].fillna("").astype(str).str.strip()
    rounds["side"] = rounds["side"].fillna("").astype(str).str.strip()
    rounds["site_hit"] = rounds["site_hit"].fillna("").astype(str).str.strip()

    if rounds["won"].dropna().max() > 1:
        raise HTTPException(status_code=400, detail="'won' must be 0/1. Check rounds.csv.")
    if rounds["traded_within_5s"].dropna().max() > 1:
        raise HTTPException(status_code=400, detail="'traded_within_5s' must be 0/1. Check rounds.csv.")

    total_rounds = int(len(rounds))
    lost = rounds[rounds["won"] == 0].copy()
    lost_rounds = int(len(lost))

    def classify(row) -> str:
        fd_player = row["first_death_player"]
        traded = row["traded_within_5s"]
        util = row["utility_used_before_first_death"]

        # If we don't have FD info, we can't diagnose early-round causes
        if fd_player == "":
            return "No First-Death Logged"

        # Strongest known lever from your dataset
        if traded == 0:
            # refinement: was it also dry?
            if util == 0:
                return "Untraded First Death + No Utility"
            return "Untraded First Death"

        # traded == 1 but still lost
        if util == 0:
            return "Traded First Death But No Utility (Follow-up Failed)"
        return "Traded First Death But Still Lost (Mid-round Issue)"

    if lost_rounds == 0:
        return {
            "filters": {"map": map, "side": side, "site": site},
            "total_rounds": total_rounds,
            "lost_rounds": 0,
            "message": "No lost rounds in current filter set."
        }

    lost["cause"] = lost.apply(classify, axis=1)

    # Cause summary
    summary = (
        lost.groupby("cause", as_index=False)
        .agg(rounds=("cause", "count"))
        .sort_values(by="rounds", ascending=False)
    )
    summary["share_pct"] = (summary["rounds"] / max(lost_rounds, 1) * 100).round(1)

    # Provide a few example rounds per cause (coach-friendly)
    examples = []
    per_cause = {}
    for _, row in lost.iterrows():
        cause = row["cause"]
        if per_cause.get(cause, 0) >= max(1, int(limit_examples)):
            continue
        per_cause[cause] = per_cause.get(cause, 0) + 1
        examples.append({
            "cause": cause,
            "match_id": int(row["match_id"]) if pd.notna(row["match_id"]) else None,
            "round_number": int(row["round_number"]) if pd.notna(row["round_number"]) else None,
            "side": row["side"],
            "site_hit": row["site_hit"],
            "first_death_player": row["first_death_player"],
            "first_death_role": row["first_death_role"],
            "traded_within_5s": int(row["traded_within_5s"]) if pd.notna(row["traded_within_5s"]) else None,
            "utility_used_before_first_death": int(row["utility_used_before_first_death"]) if pd.notna(row["utility_used_before_first_death"]) else None,
        })

    # Build response list
    causes = []
    for _, r in summary.iterrows():
        causes.append({
            "cause": r["cause"],
            "lost_rounds": int(r["rounds"]),
            "share_pct": float(r["share_pct"]),
        })

    return {
        "filters": {"map": map, "side": side, "site": site},
        "total_rounds": total_rounds,
        "lost_rounds": lost_rounds,
        "causes": causes,
        "examples": examples,
        "notes": [
            "v1 autopsy assigns one primary cause per lost round using simple heuristics.",
            "Next improvement: add multi-tag causes + clutch/economy signals if you add more columns."
        ]
    }
from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str
    map: Optional[str] = None
    side: Optional[str] = None
    site: Optional[str] = None

@app.post("/chat")
def chat(req: ChatRequest):
    msg = (req.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="message is required")

    # Pull live analytics under the same filters as the dashboard
    fd = first_deaths_insights(min_fd=2, map=req.map, side=req.side, site=req.site)
    trades = trade_insights(min_fd=2, map=req.map, side=req.side, site=req.site)
    autopsy = round_autopsy(map=req.map, side=req.side, site=req.site, limit_examples=6)

    # Always have a strong fallback
    top_cause = (autopsy.get("causes") or [{}])[0]
    fallback = (
        f"Filters: map={req.map or 'ALL'}, side={req.side or 'ALL'}, site={req.site or 'ALL'}\n"
        f"Baseline win rate: {fd.get('baseline_round_win_pct')}%\n"
        f"Trade rate: {trades.get('team_trade_summary', {}).get('trade_rate_pct')}%\n"
        f"Top loss cause: {top_cause.get('cause','N/A')} ({top_cause.get('share_pct','—')}% of losses)\n\n"
        "Ask me: 'What drills fix this?', 'What should Entry do?', or 'Summarize our autopsy.'"
    )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"mode": "rule_based", "answer": fallback}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        prompt = f"""
You are a VALORANT assistant coach. Answer the user using ONLY the analytics below.
If the question requires data we don't have, say what is missing and suggest a workaround.
Keep it concise, specific, and coaching-oriented.

Filters:
map={req.map}, side={req.side}, site={req.site}

ANALYTICS:
FIRST_DEATHS={fd}
TRADES={trades}
ROUND_AUTOPSY={autopsy}

User question: {msg}

Output format:
1) Direct answer (2–5 sentences)
2) 3 actionable bullets
3) (Optional) 1 drill for tomorrow
""".strip()

        resp = client.responses.create(
            model="gpt-4o-mini",
            input=prompt,
            temperature=0.4,
        )

        text = ""
        for item in getattr(resp, "output", []):
            if hasattr(item, "content"):
                for c in item.content:
                    if getattr(c, "type", "") == "output_text":
                        text += c.text

        text = text.strip()
        if not text:
            text = fallback

        return {"mode": "ai", "answer": text}

    except Exception as e:
        return {"mode": "fallback", "answer": fallback, "error": str(e)}

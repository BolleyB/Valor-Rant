🎯 Valor-Rant — AI-Powered VALORANT Coaching & Analytics Platform

Valor-Rant is an AI-powered esports analytics and coaching assistant built for competitive VALORANT teams.
It transforms raw match round data into actionable coaching insights by identifying micro-level mistakes that cause macro-level losses — then generates targeted coaching plans and practice drills automatically.

Instead of just showing stats, Valor-Rant functions as a real assistant coach.

🚀 Features
Feature	Description
First Death Impact Engine	Identifies which players’ early deaths cost the most rounds
Trade Discipline Analyzer	Measures spacing and coordination failures
Round Autopsy System	Automatically classifies lost rounds by root cause
AI Coach Report Generator	Produces scrim-ready coaching briefs & practice plans
Coach Chat Assistant	Ask natural-language questions about team weaknesses
Interactive Dashboard	Real-time charts, filters, and performance breakdowns
Map / Site / Side Filters	Deep situational analysis
OpenAI Powered (with fallback)	AI recommendations with deterministic rule-based safety
🧠 Why Valor-Rant is Different

Traditional esports dashboards display stats.
Valor-Rant answers the real coaching question:

Why are we losing rounds — and what do we fix next?

It directly maps:

Player mistake → Round outcome → Coaching action


Making it a true decision-support system for esports staff.

⚙️ Tech Stack

• FastAPI backend
• OpenAI GPT-4o / GPT-4.1
• Pandas analytics engine
• Chart.js interactive frontend
• CSV-based match ingestion
• Modular & extensible architecture

🧪 Example Outputs

• First-death impact breakdown
• Trade success vs loss correlation
• Automated round loss autopsy
• AI-generated practice plans
• Natural-language coach chat assistant

🛠 Setup
git clone https://github.com/BolleyB/Valor-Rant.git
cd Valor-Rant

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

echo "OPENAI_API_KEY=YOUR_KEY_HERE" > backend/.env

uvicorn backend.app.main:app --reload


Open:

http://localhost:8000/dashboard

📈 Use Cases

• Scrim review automation
• VOD review prep
• Practice planning
• Player development tracking
• Competitive analytics tooling

🏆 Author

Hugo Bolivar Webster III
Lead Engineer & AI Systems Developer
Atlanta, GA

📜 License

MIT License

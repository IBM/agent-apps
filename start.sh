#!/bin/sh
# Start all cuga demo apps as background processes inside the container.
# The container stays alive as long as at least one process runs.

APP_DIR=/app/apps

log() { echo "[start.sh] $*"; }

cd "$APP_DIR"

log "Starting newsletter         on :18793"
python newsletter/main.py --port 18793 &

log "Starting drop_summarizer    on :18794"
python drop_summarizer/main.py --port 18794 &

log "Starting web_researcher     on :18798"
python web_researcher/main.py --port 18798 &

log "Starting voice_journal      on :18799"
python voice_journal/main.py --port 18799 &

log "Starting smart_todo         on :18800"
python smart_todo/main.py --port 18800 &

log "Starting server_monitor     on :8767"
python server_monitor/main.py --port 8767 &

log "Starting stock_alert        on :18801"
python stock_alert/main.py --port 18801 &

log "Starting video_qa           on :8766"
python video_qa/run.py --web --port 8766 &

log "Starting travel_planner     on :8090"
PORT=8090 python travel_planner/main.py &

log "Starting deck_forge         on :18802"
python deck_forge/main.py --port 18802 &

log "Starting youtube_research   on :18803"
python youtube_research/main.py --port 18803 &

log "Starting arch_diagram       on :18804"
python arch_diagram/main.py --port 18804 &

log "Starting hiking_research    on :18805"
python hiking_research/main.py --port 18805 &

log "Starting movie_recommender  on :18806"
python movie_recommender/main.py --port 18806 &

log "Starting webpage_summarizer on :8071"
python webpage_summarizer/main.py --port 8071 &

log "Starting code_reviewer      on :18807"
python code_reviewer/main.py --port 18807 &

log "All apps launched. Waiting..."
wait

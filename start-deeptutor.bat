@echo off
cd /d D:\deepseek
echo Starting DeepTutor (dev mode)...
python scripts/docker_compose.py -f docker-compose.yml -f docker-compose.dev.yml up -d
echo.
echo Web UI: http://localhost:3782
echo Knowledge: http://localhost:3782/knowledge
echo Figures: http://localhost:8100/api/kb/figures/gallery?kb_name=child_knowledge_base
echo.
pause

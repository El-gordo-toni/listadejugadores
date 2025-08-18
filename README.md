# Matungo Golf – Render-ready

1) Subí a GitHub.
2) En Render: New → Web Service → repo.
3) Build: pip install -r requirements.txt
   Start: gunicorn -k eventlet -w 1 app:app
4) Env vars: ADMIN_KEY, DATA_JSON (opcional)

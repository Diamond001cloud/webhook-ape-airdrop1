Webhook deployment (brief)

1) Environment variables (set in host dashboard)
- APECOIN_BOT_TOKEN
- APECOIN_ADMIN_ID
- WEBHOOK_URL (e.g. https://your-service.onrender.com)
- Optionally WEBHOOK_PATH (defaults to token), PORT(8443)
- Other variables from `.env.example` in deploy_workspace if needed

2) Deploy to Render (Web Service)
- Create new Web Service, point to repo and branch
- Set build to use default (Render auto-detect) or use Dockerfile
- Start command (if not using Docker): python webhook_workspace/webhook_bot.py
- Set environment variable WEBHOOK_URL to your service's public URL
- Deploy and check logs; the bot sets webhook to WEBHOOK_URL/WEBHOOK_PATH

3) Local test with ngrok (optional)
- Run: `ngrok http 8443` and set WEBHOOK_URL to the forwarded URL
- Run the bot locally: python webhook_workspace/webhook_bot.py

Notes
- This uses the built-in webhook server in python-telegram-bot and will set the webhook automatically if WEBHOOK_URL is provided.
- I preserved your gas/bonus messages unchanged.

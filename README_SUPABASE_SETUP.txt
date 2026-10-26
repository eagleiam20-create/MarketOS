MarketOS — Supabase connection fix
==================================

IMPORTANT: This package contains the backend plus your original templates and static files.
It does NOT contain your .env or SQLite database.

INSTALL
1) Stop the currently running server (CMD: Ctrl+C).
2) Extract this ZIP into a NEW folder first, e.g. MarketOS_Supabase_Fixed. Do not delete your old project.
3) Copy your existing .env into this new folder (do not share it or upload it publicly).
4) Confirm .env has these values (names must match exactly):
   SUPABASE_URL=https://YOUR-PROJECT.supabase.co
   SUPABASE_SECRET_KEY=YOUR_SERVER-SIDE-SECRET-KEY
   MARKETOS_SESSION_SECRET=some-long-random-private-string
   MARKETOS_ADMIN_KEY=some-long-random-admin-key
   COOKIE_SECURE=false
5) In CMD, cd to the extracted folder, then run:
   python -m pip install -r requirements.txt
   python -m uvicorn main:app --reload
6) Visit http://127.0.0.1:8000/api/health
   Expected: {"app":"MarketOS","status":"ok","database":"supabase",...}
7) Visit http://127.0.0.1:8000/

If you do not set MARKETOS_SESSION_SECRET or MARKETOS_ADMIN_KEY, the app will still start locally using the same demo defaults as your old app. For any public deployment, set both to long private values. Admin demo key is change-this-admin-key unless you override it.

TROUBLESHOOTING
- If /api/health returns 503, check the exact SUPABASE_URL and SUPABASE_SECRET_KEY in .env and ensure the service/secret key has the required table permissions.
- If startup says missing SUPABASE_URL or key, the .env file must be in the same folder as main.py. Ensure it is named exactly .env (not .env.txt).
- Never put the Supabase secret key in HTML/JavaScript or a public repository. Rotate it if it was exposed in an archive.
- Images still upload to local static/uploads, so they are not persistent on a public host. Supabase Storage migration is a separate step.
- Payment creation only creates a PENDING demo record. No live payment provider is connected.
- Test all features locally before public deployment.

ADDITIONAL FEATURES
- Owner controller: /owner?key=YOUR_MARKETOS_ADMIN_KEY
- Order status can notify customers in the dashboard with estimated ready time (5–30 minutes).
- Run SUPABASE_NOTIFICATIONS_MIGRATION.sql once in Supabase SQL Editor before using order notifications.
- Notifications are in-app only, not SMS/WhatsApp/push. Customers see them in dashboard after refresh.
- Controller uses MARKETOS_ADMIN_KEY; keep it private.

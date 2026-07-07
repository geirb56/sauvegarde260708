# CardioCoach Troubleshooting Guide

## Common Issues and Solutions

### Issue: "Error loading page - Domain: undefined - net::ERR_NAME_NOT_RESOLVED"

**Symptoms:**
- Mobile/desktop preview shows blank page with DNS error
- Error message indicates "Domain: undefined"
- API calls failing with "undefined" in the URL

**Root Cause:**
React environment variables (`REACT_APP_BACKEND_URL`) are not loaded properly when the development server starts. This typically happens after:
- Git pull/clone operations
- Service restarts without proper environment loading
- Changes to `.env` files

**Solution:**

1. **Verify .env file exists:**
   ```bash
   cat /app/frontend/.env
   ```
   Should show: `REACT_APP_BACKEND_URL=https://charge-load.preview.emergentagent.com`

2. **Restart frontend service:**
   ```bash
   sudo supervisorctl stop frontend
   sleep 2
   sudo supervisorctl start frontend
   ```

3. **Wait for compilation:**
   ```bash
   tail -f /var/log/supervisor/frontend.*.log
   ```
   Look for: "Compiled successfully!"

4. **Verify fix:**
   - Check preview URL loads correctly
   - Verify API calls are working:
     ```bash
     curl https://charge-load.preview.emergentagent.com/api/training/plan?user_id=default
     ```

**Prevention:**
The app now includes a robust config module (`/app/frontend/src/config.js`) that:
- Provides fallback handling if env var is undefined
- Logs configuration in development mode
- Uses `window.location.origin` as fallback

**Files involved:**
- `/app/frontend/.env` - Environment variables
- `/app/frontend/src/config.js` - Config module with fallbacks
- `/app/frontend/src/utils/constants.js` - Imports from config

---

### Issue: Services not starting after git pull

**Solution:**
```bash
cd /app
sudo supervisorctl restart all
sleep 10
sudo supervisorctl status
```

---

### Issue: MongoDB connection errors

**Solution:**
Check MongoDB is running:
```bash
sudo supervisorctl status mongodb
tail -n 50 /var/log/supervisor/mongodb.*.log
```

Verify connection string in backend:
```bash
cat /app/backend/.env | grep MONGO_URL
```

---

### Issue: Backend API not responding

**Solution:**
Check backend logs:
```bash
tail -n 100 /var/log/supervisor/backend.*.log
```

Restart backend:
```bash
sudo supervisorctl restart backend
```

Test backend:
```bash
curl http://localhost:8001/api/training/plan?user_id=default
```

---

## Service Management

**View all services:**
```bash
sudo supervisorctl status
```

**Restart all services:**
```bash
sudo supervisorctl restart all
```

**View logs:**
```bash
# Backend
tail -f /var/log/supervisor/backend.*.log

# Frontend
tail -f /var/log/supervisor/frontend.*.log

# MongoDB
tail -f /var/log/supervisor/mongodb.*.log
```

---

## Environment Variables

### Frontend (.env)
- `REACT_APP_BACKEND_URL` - Backend API URL (required)
- `WDS_SOCKET_PORT` - Webpack dev server socket port
- `ENABLE_HEALTH_CHECK` - Health check feature flag

### Backend (.env)
- `MONGO_URL` - MongoDB connection string
- `DB_NAME` - Database name
- `CORS_ORIGINS` - CORS allowed origins
- `STRAVA_CLIENT_ID` - Strava OAuth client ID
- `STRAVA_CLIENT_SECRET` - Strava OAuth secret
- `STRIPE_API_KEY` - Stripe payment API key

---

## Quick Recovery Steps

If the app is completely broken:

1. **Pull latest code:**
   ```bash
   cd /app && git pull origin main
   ```

2. **Restart all services:**
   ```bash
   sudo supervisorctl restart all
   ```

3. **Check service status:**
   ```bash
   sudo supervisorctl status
   ```

4. **Verify app loads:**
   - Visit: https://charge-load.preview.emergentagent.com
   - Check console for errors

5. **If still broken, check logs:**
   ```bash
   tail -n 100 /var/log/supervisor/backend.*.log
   tail -n 100 /var/log/supervisor/frontend.*.log
   ```

---

## Contact

For issues not covered here, check:
- `/app/memory/PRD.md` - Product requirements and architecture
- `/app/README.md` - Project overview
- Backend logs in `/var/log/supervisor/`

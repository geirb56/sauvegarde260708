from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
from app.credential_vault import CredentialVault
from tasks.sync_tasks import sync_user

app = FastAPI(title="CardioCoach API")

vault = CredentialVault(redis_url=os.getenv("REDIS_URL"), master_key_b64=os.getenv("MASTER_KEY"))

class GarminConnectRequest(BaseModel):
    user_id: str
    garmin_username: str
    garmin_password: str

@app.post("/auth/garmin/connect", status_code=202)
def connect_garmin(req: GarminConnectRequest):
    # TLS required at edge. Never return credentials or tokens to the client.
    token = vault.store_temp_credentials(user_id=req.user_id, username=req.garmin_username, password=req.garmin_password)
    # schedule background sync
    sync_user.apply_async(args=[req.user_id], queue="SYNC_USER")
    return {"status": "scheduled"}

@app.post("/sync/manual")
def manual_sync(user_id: str):
    sync_user.apply_async(args=[user_id], queue="SYNC_USER")
    return {"status": "scheduled"}

@app.get("/health")
def health():
    return {"status": "ok"}

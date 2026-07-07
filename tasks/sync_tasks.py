from celery import Celery
from celery.utils.log import get_task_logger
import os

celery = Celery("workers")
celery.conf.broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
celery.conf.result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")
logger = get_task_logger(__name__)

# Local imports delayed to avoid import cycles in Docker build
from app.credential_vault import CredentialVault
from app.gccli_runner import GccliRunner
from app.providers.gccli_provider import GccliProvider

vault = CredentialVault(redis_url=os.getenv("REDIS_URL"), master_key_b64=os.getenv("MASTER_KEY"))
runner = GccliRunner(gccli_path=os.getenv("GCCLI_PATH", "gccli"))
provider = GccliProvider(credential_vault=vault, runner=runner)

@celery.task(bind=True, max_retries=3, acks_late=True)
def sync_user(self, user_id: str, since: str | None = None):
    # Minimal example: call provider.sync_activities and enqueue processing tasks
    try:
        activities = provider.sync_activities(user_id, since=since)
        for a in activities:
            process_activity.delay(user_id, a)
    except Exception as exc:
        logger.exception("sync_user failed for %s", user_id)
        raise self.retry(exc=exc, countdown=10)

@celery.task(bind=True)
def process_activity(self, user_id: str, activity_raw: dict):
    # placeholder: parse and store in DB, then schedule metrics computation
    logger.info("Processing activity for user %s: %s", user_id, activity_raw.get("external_id"))

@celery.task(bind=True)
def compute_metrics(self, user_id: str, activity_id: str):
    # placeholder compute
    logger.info("Compute metrics for activity %s of user %s", activity_id, user_id)

"""Lightweight Redis-backed job queue for Garmin sync.

Kept intentionally minimal: a single Redis list acts as the queue, workers
consume it out-of-process. No Celery / RQ magic, no microservices.
"""

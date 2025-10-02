# CityFlow — Overview

**Date:** 2025-10-02

CityFlow is a lightweight transport simulation + AI insights demo designed for rapid, reliable deployment on Google Cloud Run. It bundles a FastAPI backend, a multi‑page static frontend, and a simple simulation engine into a single container.

## Goals
- Demonstrate an end‑to‑end “data → simulation → insights” flow with minimal infra.
- Be cloud‑portable and cheap at idle (scale to zero).
- Provide a small but realistic API surface with jobs, status polling, and generated artifacts.
- Support RAG‑style documentation search via local project docs (this folder).

## High‑level Features
- **FastAPI** service with namespaced endpoints under `/v1`.
- **Multi‑page frontend** served by the same process (no second web server).
- **Job orchestration** pattern for simulations: submit → poll → results.
- **Files mount** at `/files` for downloading generated results.
- **Optional LLM** features for insights/chat with `OPENAI_API_KEY`.
- **Cloud Run**: one container, scale to zero, cold start tolerant.

## Typical User Journey
1. User opens `/simulate.html` and selects a city/parameters.
2. Client calls `POST /v1/submit` to start a simulation.
3. Client polls `GET /v1/status/{job_id}` until `status=finished`.
4. Client opens `/sim_results.html?job_id=...` to view/download artifacts.
5. User requests `/v1/insights` (and optionally `/v1/chat`) for explanation/Q&A.

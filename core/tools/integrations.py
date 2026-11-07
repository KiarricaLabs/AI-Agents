"""Integration tools (Stage 4.1) — consequential, human-gated."""
from __future__ import annotations
from core.tools import Tool
from typing import Any, Dict, Optional


def _ctx(context):
    ctx = context or {}
    return ctx.get("db"), ctx.get("tenant_id"), ctx.get("user_id")


class EmailSendTool(Tool):
    name = "email_send"
    description = "Send an email via SMTP (human-gated)."
    consequential = True

    def run(self, args, context=None):
        db, tenant, user = _ctx(context)
        from storage.credentials import CredentialStore
        store = CredentialStore(db=db, tenant_id=tenant, user_id=user)
        from integrations.email import EmailIntegration
        integ = EmailIntegration(credential_store=store, tenant_id=tenant, user_id=user)
        integ.connect({})
        params = {
            "to": args.get("to"),
            "subject": args.get("subject", ""),
            "body": args.get("body", ""),
        }
        result = integ.execute("send", params, approved=True)
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "send failed"))
        return result


class CalendarCreateTool(Tool):
    name = "calendar_create"
    description = "Create a Google Calendar event (human-gated)."
    consequential = True

    def run(self, args, context=None):
        db, tenant, user = _ctx(context)
        from storage.credentials import CredentialStore
        store = CredentialStore(db=db, tenant_id=tenant, user_id=user)
        from integrations.calendar import CalendarIntegration
        integ = CalendarIntegration(credential_store=store, tenant_id=tenant, user_id=user)
        integ.connect({})
        params = {
            "title": args.get("title"),
            "description": args.get("description", ""),
            "start": args.get("start"),
            "end": args.get("end"),
            "timezone": args.get("timezone", "UTC"),
            "location": args.get("location"),
        }
        result = integ.execute("create_event", params, approved=True)
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "create failed"))
        return result


class ImageGenerateTool(Tool):
    name = "image_generate"
    description = "Generate an image (human-gated)."
    consequential = True

    def run(self, args, context=None):
        db, tenant, user = _ctx(context)
        from storage.credentials import CredentialStore
        store = CredentialStore(db=db, tenant_id=tenant, user_id=user)
        from integrations.media import MediaIntegration
        integ = MediaIntegration(credential_store=store, tenant_id=tenant, user_id=user)
        integ.connect({})
        params = {
            "prompt": args.get("prompt"),
            "size": args.get("size", "1024x1024"),
            "quality": args.get("quality"),
        }
        result = integ.execute("generate", params, approved=True)
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "generate failed"))
        return result
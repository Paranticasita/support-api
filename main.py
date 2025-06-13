# support-api/main.py（完全独立）
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import os
from google.cloud import firestore
from pydantic import BaseModel
import uuid
from datetime import datetime, timezone

app = FastAPI(title="Portfolio Support System")

# CORSはメインアプリドメインのみ許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://your-main-app.vercel.app",
        "http://localhost:3000"  # 開発環境
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静的ファイルとテンプレート（独立したUI）
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Firestore初期化（独立）
firestore_client = firestore.Client()

class SupportTicket(BaseModel):
    subject: str
    message: str
    category: str = "general"
    user_id: str
    email: str
    analysis_id: str = None

@app.get("/support", response_class=HTMLResponse)
async def support_form(request: Request, user: str = None, email: str = None, token: str = None):
    """サポートフォーム表示（独立したHTMLページ）"""
    
    # 簡易認証チェック
    if not user or not email:
        return templates.TemplateResponse("auth_required.html", {"request": request})
    
    # トークン検証（オプション）
    user_info = {
        "user_id": user,
        "email": email,
        "verified": True  # 実装段階では簡易チェック
    }
    
    return templates.TemplateResponse("support_form.html", {
        "request": request,
        "user_info": user_info
    })

@app.get("/report-issue", response_class=HTMLResponse) 
async def report_issue_form(request: Request, analysisId: str = None, user: str = None, email: str = None):
    """分析問題報告フォーム（事前入力済み）"""
    
    if not user or not email:
        return templates.TemplateResponse("auth_required.html", {"request": request})
    
    pre_filled_data = {
        "category": "technical",
        "subject": f"分析ID {analysisId} で問題が発生",
        "analysis_id": analysisId,
        "user_info": {"user_id": user, "email": email}
    }
    
    return templates.TemplateResponse("issue_report_form.html", {
        "request": request,
        "pre_filled": pre_filled_data
    })

@app.post("/api/tickets")
async def create_ticket(ticket: SupportTicket):
    """チケット作成（完全独立）"""
    try:
        ticket_id = str(uuid.uuid4())
        ticket_data = {
            "ticket_id": ticket_id,
            "user_id": ticket.user_id,
            "email": ticket.email,
            "subject": ticket.subject,
            "message": ticket.message,
            "category": ticket.category,
            "analysis_id": ticket.analysis_id,
            "status": "open",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "responses": []
        }
        
        # 独立したFirestoreコレクション
        firestore_client.collection("support_tickets").document(ticket_id).set(ticket_data)
        
        return JSONResponse({
            "status": "success",
            "ticket_id": ticket_id,
            "message": "お問い合わせを受け付けました"
        })
        
    except Exception as e:
        raise HTTPException(500, f"チケット作成に失敗: {str(e)}")
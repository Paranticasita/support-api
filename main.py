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
import google.generativeai as genai
from typing import List, Dict, Any

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

# Gemini AI初期化（API Key使用）
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.0-flash-exp')

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

# 管理画面用のルート
@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """管理者ダッシュボード"""
    try:
        # 全チケット取得
        tickets_ref = firestore_client.collection("support_tickets")
        tickets = tickets_ref.order_by("created_at", direction=firestore.Query.DESCENDING).limit(50).stream()
        
        ticket_list = []
        for ticket in tickets:
            ticket_data = ticket.to_dict()
            ticket_data['id'] = ticket.id
            ticket_list.append(ticket_data)
        
        # AI分析実行
        analysis = await analyze_tickets_with_ai(ticket_list)
        
        return templates.TemplateResponse("admin_dashboard.html", {
            "request": request,
            "tickets": ticket_list,
            "analysis": analysis,
            "total_tickets": len(ticket_list)
        })
        
    except Exception as e:
        raise HTTPException(500, f"ダッシュボード取得エラー: {str(e)}")

@app.get("/admin/ticket/{ticket_id}", response_class=HTMLResponse)
async def ticket_detail(request: Request, ticket_id: str):
    """チケット詳細表示"""
    try:
        doc = firestore_client.collection("support_tickets").document(ticket_id).get()
        if not doc.exists:
            raise HTTPException(404, "チケットが見つかりません")
        
        ticket_data = doc.to_dict()
        ticket_data['id'] = doc.id
        
        # 個別AI分析
        ai_insight = await analyze_single_ticket(ticket_data)
        
        return templates.TemplateResponse("ticket_detail.html", {
            "request": request,
            "ticket": ticket_data,
            "ai_insight": ai_insight
        })
        
    except Exception as e:
        raise HTTPException(500, f"チケット詳細取得エラー: {str(e)}")

@app.post("/admin/ticket/{ticket_id}/respond")
async def respond_to_ticket(ticket_id: str, response: dict):
    """チケットに返信"""
    try:
        doc_ref = firestore_client.collection("support_tickets").document(ticket_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            raise HTTPException(404, "チケットが見つかりません")
        
        ticket_data = doc.to_dict()
        new_response = {
            "id": str(uuid.uuid4()),
            "message": response.get("message"),
            "responder": response.get("responder", "admin"),
            "created_at": datetime.now(timezone.utc)
        }
        
        ticket_data["responses"].append(new_response)
        ticket_data["updated_at"] = datetime.now(timezone.utc)
        ticket_data["status"] = response.get("status", ticket_data["status"])
        
        doc_ref.update(ticket_data)
        
        return JSONResponse({"status": "success", "message": "返信を追加しました"})
        
    except Exception as e:
        raise HTTPException(500, f"返信追加エラー: {str(e)}")

async def analyze_tickets_with_ai(tickets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """AIを使ってチケット全体を分析"""
    try:
        if not tickets:
            return {"summary": "チケットがありません", "insights": [], "recommendations": []}
        
        # チケット情報を整理
        ticket_summaries = []
        for ticket in tickets[:10]:  # 最新10件を分析
            summary = f"ID: {ticket.get('ticket_id', '')}, カテゴリ: {ticket.get('category', '')}, 件名: {ticket.get('subject', '')}, 内容: {ticket.get('message', '')[:100]}"
            ticket_summaries.append(summary)
        
        prompt = f"""
以下のサポートチケット情報を分析して、以下の形式でJSONレスポンスを生成してください：

チケット情報:
{chr(10).join(ticket_summaries)}

以下の形式で分析結果を返してください：
{{
  "summary": "全体的な傾向の要約（3-4行）",
  "common_issues": ["よくある問題1", "よくある問題2", "よくある問題3"],
  "insights": [
    "ユーザーのニーズに関するインサイト1",
    "システム改善のヒント1", 
    "新機能開発のアイデア1"
  ],
  "recommendations": [
    "短期的な改善提案1",
    "中長期的な開発提案1",
    "ユーザー体験向上提案1"
  ]
}}
"""
        
        response = model.generate_content(prompt)
        
        # JSONパース試行
        import json
        import re
        try:
            # JSONコードブロックを除去
            clean_text = response.text
            # ```json から ``` までを削除
            clean_text = re.sub(r'```json\s*', '', clean_text)
            clean_text = re.sub(r'```.*$', '', clean_text, flags=re.MULTILINE)
            # 先頭末尾の空白を削除
            clean_text = clean_text.strip()
            
            analysis_result = json.loads(clean_text)
        except:
            # パースに失敗した場合のフォールバック
            analysis_result = {
                "summary": response.text[:200] + "...",
                "common_issues": ["分析中", "データ処理中"],
                "insights": ["AI分析を実行中です"],
                "recommendations": ["分析結果を確認中です"]
            }
        
        return analysis_result
        
    except Exception as e:
        return {
            "summary": f"AI分析エラー: {str(e)}",
            "common_issues": ["分析エラー"],
            "insights": ["AI分析が利用できません"],
            "recommendations": ["手動での分析をお勧めします"]
        }

async def analyze_single_ticket(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """個別チケットのAI分析"""
    try:
        prompt = f"""
以下のサポートチケットを分析してください：

件名: {ticket.get('subject', '')}
カテゴリ: {ticket.get('category', '')}
内容: {ticket.get('message', '')}
ユーザー: {ticket.get('email', '')}

以下の形式でJSONレスポンスを生成してください：
{{
  "urgency": "高/中/低",
  "category_suggestion": "適切なカテゴリ",
  "response_suggestion": "推奨される返信内容",
  "related_improvements": ["関連する改善提案1", "関連する改善提案2"]
}}
"""
        
        response = model.generate_content(prompt)
        
        import json
        import re
        try:
            # JSONコードブロックを除去
            clean_text = response.text
            clean_text = re.sub(r'```json\s*', '', clean_text)
            clean_text = re.sub(r'```.*$', '', clean_text, flags=re.MULTILINE)
            clean_text = clean_text.strip()
            
            insight = json.loads(clean_text)
        except:
            insight = {
                "urgency": "中",
                "category_suggestion": ticket.get('category', 'general'),
                "response_suggestion": "詳細を確認して適切に対応してください。",
                "related_improvements": ["ユーザーガイドの改善", "エラーメッセージの見直し"]
            }
        
        return insight
        
    except Exception as e:
        return {
            "urgency": "不明",
            "category_suggestion": "分析エラー",
            "response_suggestion": f"AI分析エラー: {str(e)}",
            "related_improvements": ["手動分析が必要です"]
        }
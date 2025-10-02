import logging
from fastapi import APIRouter, HTTPException

from api.models import ChatRequest, ChatResponse, ChatMessage
from api.globals import _get_rag_context, _answer_with_rag_context

log = logging.getLogger("cityflow.api")

router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """
    Chat endpoint: accepts {messages:[{role,content}...]} and returns
    { "message": { "role": "assistant", "content": "..." } }
    """
    print(req)
    try:
        user_text = req.messages[-1].content
       
        # Get RAG context for the query
        rag_context = _get_rag_context(user_text)

        # Answer with context
        answer = _answer_with_rag_context(user_text, rag_context)
        return ChatResponse(message=ChatMessage(role="assistant", content=answer))
    except HTTPException:
        raise
    except Exception as e:
        log.exception("chat failed")
        raise HTTPException(status_code=500, detail=str(e))
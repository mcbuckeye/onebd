"""Export comp sets and DD packages to PowerPoint and PDF."""
import structlog
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import io
from unified_api.services.auth import TokenData
from unified_api.routers.auth import get_current_user

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/export", tags=["Export Docs"])


class CompExportRequest(BaseModel):
    title: str = "Comparable Deal Analysis"
    criteria: Dict[str, Any] = {}
    deals: List[Dict[str, Any]]
    stats: Dict[str, Any] = {}


class DDExportRequest(BaseModel):
    company_name: str
    dd_package: Dict[str, Any]


@router.post("/comps/pptx")
async def export_comps_pptx(req: CompExportRequest, user: TokenData = Depends(get_current_user)):
    """Export comp set to PowerPoint."""
    from unified_api.services.export_pptx import generate_comp_pptx
    
    try:
        pptx_bytes = generate_comp_pptx(req.title, req.criteria, req.deals, req.stats)
        return StreamingResponse(
            io.BytesIO(pptx_bytes),
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": f"attachment; filename=comp-analysis.pptx"}
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="python-pptx not installed")
    except Exception as e:
        logger.error("PPTX export failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dd/pdf")
async def export_dd_pdf(req: DDExportRequest, user: TokenData = Depends(get_current_user)):
    """Export DD package to PDF."""
    from unified_api.services.export_pptx import generate_dd_pdf
    
    try:
        pdf_bytes = generate_dd_pdf(req.company_name, req.dd_package)
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=dd-{req.company_name.lower().replace(' ', '-')}.pdf"}
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="reportlab not installed")
    except Exception as e:
        logger.error("PDF export failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

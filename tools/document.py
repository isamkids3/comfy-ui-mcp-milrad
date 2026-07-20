import os
import logging
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# Document parsing dependencies
try:
    import pypdf
except ImportError:
    pypdf = None
try:
    from docx import Document
except ImportError:
    Document = None

logger = logging.getLogger("DocumentTools")

def validate_path_in_workspace(path_str: str) -> str:
    """
    Validates that path_str resolves to a path strictly within SHARED_WORKSPACE_ROOT.
    Returns the absolute path as a string if valid, otherwise raises ValueError.
    """
    shared_root = os.getenv("SHARED_WORKSPACE_ROOT", "/Users/adamdali/Documents/AI_Agent_MR/gen-content")
    shared_root_path = Path(shared_root).resolve()
    
    # Resolve the incoming path
    try:
        resolved_path = Path(path_str).resolve()
    except Exception as e:
        raise ValueError(f"Invalid path structure: {e}")
        
    # Check nesting
    try:
        resolved_path.relative_to(shared_root_path)
    except ValueError:
        raise ValueError(f"Security error: Path '{path_str}' is outside the workspace bounds '{shared_root}'")
        
    return str(resolved_path)

def register_document_tools(mcp: FastMCP):
    """Register Document API tools"""

    @mcp.tool()
    def read_user_document(file_path: str) -> str:
        """
        USER DOCUMENT INGESTION TOOL
        Parses and extracts text content from local user uploads (.txt, .pdf, or .docx) inside the sandbox workspace, returning clean string payloads.
        """
        try:
            resolved_path = validate_path_in_workspace(file_path)
        except ValueError as e:
            return str(e)

        if not os.path.exists(resolved_path):
            return f"Error: File not found at {file_path}"
            
        ext = os.path.splitext(resolved_path)[1].lower()
        
        try:
            if ext == '.txt':
                with open(resolved_path, 'r', encoding='utf-8') as f:
                    return f.read()
            elif ext == '.pdf':
                if pypdf is None:
                    return "Error: pypdf library is not installed."
                text = []
                with open(resolved_path, 'rb') as f:
                    reader = pypdf.PdfReader(f)
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text.append(page_text)
                return "\n".join(text)
            elif ext == '.docx':
                if Document is None:
                    return "Error: python-docx library is not installed."
                doc = Document(resolved_path)
                text = [para.text for para in doc.paragraphs]
                return "\n".join(text)
            else:
                return f"Error: Unsupported file extension '{ext}'. Only .txt, .pdf, and .docx are supported."
        except Exception as e:
            logger.error(f"Failed to read document {resolved_path}: {e}")
            return f"Error reading document: {e}"

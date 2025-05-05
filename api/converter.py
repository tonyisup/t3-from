import json
import os
from datetime import datetime, timezone
from fastapi import FastAPI, File, UploadFile, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel
import asyncio
import tempfile
import shutil
from pathlib import Path
import logging
import time
import traceback
from typing import Optional, Dict, Any, List
import io

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_RESPONSE_SIZE = 50 * 1024 * 1024  # 50MB
CHUNK_SIZE = 1024 * 1024  # 1MB chunks
MAX_CONCURRENT_CONVERSIONS = 5
TEMP_DIR = Path(tempfile.gettempdir()) / "converter"
TEMP_DIR.mkdir(exist_ok=True)
TIMEOUT = 50  # 50 seconds timeout

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
active_conversions = 0
conversion_lock = asyncio.Lock()

async def cleanup_conversion(task_id: str):
    """Clean up completed conversion tasks."""
    await asyncio.sleep(300)  # Wait 5 minutes before cleanup
    if task_id in active_conversions:
        del active_conversions[task_id]

# --- Performance Monitoring ---
class PerformanceMonitor:
    def __init__(self):
        self.start_time = None
        self.metrics = {}

    def start(self):
        self.start_time = time.time()
        self.metrics = {}

    def record_metric(self, name: str, value: float):
        self.metrics[name] = value

    def get_elapsed_time(self) -> float:
        return time.time() - self.start_time if self.start_time else 0

    def get_metrics(self) -> dict:
        return {
            **self.metrics,
            "total_time": self.get_elapsed_time()
        }

# --- Helper Functions ---
def unix_to_iso(unix_timestamp: Optional[float]) -> Optional[str]:
    """Converts a Unix timestamp to an ISO 8601 string in UTC."""
    if unix_timestamp is None:
        return None
    try:
        float_timestamp = float(unix_timestamp)
        dt_object = datetime.fromtimestamp(float_timestamp, tz=timezone.utc)
        return dt_object.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    except (TypeError, ValueError) as e:
        logger.warning(f"Could not convert timestamp {unix_timestamp}: {e}")
        return datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

def extract_text_content(content_obj: dict) -> str:
    """Extracts and joins text parts from the OpenAI content object."""
    if not content_obj or 'parts' not in content_obj or not isinstance(content_obj['parts'], list):
        return ""
    
    text_parts = []
    for part in content_obj['parts']:
        if isinstance(part, str):
            text_parts.append(part)
        elif isinstance(part, dict) and part.get("content_type") == "text":
             text_parts.append(part.get("text", ""))

    return "\n".join(p for p in text_parts if p).strip()

def validate_json_structure(data: Any) -> bool:
    """Validates the basic structure of the OpenAI export JSON."""
    if not isinstance(data, dict):
        return False
    
    # Check for required top-level keys
    required_keys = ['conversations', 'current_model']
    if not all(key in data for key in required_keys):
        return False
    
    # Check conversations array
    if not isinstance(data['conversations'], list):
        return False
    
    return True

async def process_conversation_stream(file_stream: io.BytesIO, monitor: PerformanceMonitor) -> dict:
    """Processes the conversation data from a file stream using ijson and yields converted data."""
    all_threads = []
    all_messages = []
    processed_conversation_ids = set()
    message_count = 0
    thread_count = 0

    logger.info("Starting conversion process...")
    start_time = time.time()
    
    try:
        # First, validate the JSON structure
        file_stream.seek(0)
        try:
            first_item = next(ijson.items(file_stream, 'item'))
            if not validate_json_structure(first_item):
                raise ValueError("Invalid JSON structure: File does not match OpenAI export format")
            file_stream.seek(0)
        except StopIteration:
            raise ValueError("Empty JSON file")
        except Exception as e:
            raise ValueError(f"Invalid JSON format: {str(e)}")

        conversations = ijson.items(file_stream, 'item')

        for i, conversation in enumerate(conversations):
            if not isinstance(conversation, dict):
                logger.warning(f"Skipping item {i} as it's not a dictionary.")
                continue

            thread_id = conversation.get('conversation_id') or conversation.get('id')
            if not thread_id:
                logger.warning(f"Skipping conversation {i} due to missing ID.")
                continue
                
            if thread_id in processed_conversation_ids:
                logger.warning(f"Duplicate conversation ID {thread_id} found. Skipping subsequent entries.")
                continue
            processed_conversation_ids.add(thread_id)

            thread_count += 1
            if thread_count % 100 == 0:
                logger.info(f"Processed {thread_count} threads...")
                # Allow other tasks to run
                await asyncio.sleep(0)

            conversation_messages = []
            mapping = conversation.get('mapping', {})
            if not isinstance(mapping, dict):
                logger.warning(f"Invalid 'mapping' format for thread {thread_id}. Skipping messages.")
                mapping = {}

            for node_id, node in mapping.items():
                if not isinstance(node, dict) or node.get('message') is None:
                    continue

                message = node.get('message')
                if not isinstance(message, dict):
                    logger.warning(f"Invalid message structure in node {node_id} for thread {thread_id}")
                    continue

                msg_id = message.get('id')
                author_info = message.get('author', {})
                role = author_info.get('role') if isinstance(author_info, dict) else 'unknown'
                content_text = extract_text_content(message.get('content'))
                create_time = message.get('create_time')
                model_slug = message.get('metadata', {}).get('model_slug') if isinstance(message.get('metadata'), dict) else None
                status = message.get('status', 'unknown')

                if not msg_id or not role or create_time is None or not content_text:
                    continue

                message_count += 1
                conversation_messages.append({
                    'id': msg_id,
                    'threadId': thread_id,
                    'role': role,
                    'content': content_text,
                    'created_at': create_time, 
                    'model': model_slug,
                    'status': status,
                })

            if not conversation_messages:
                logger.info(f"Thread {thread_id} had no valid messages after filtering, skipping.")
                continue
                
            conversation_messages.sort(key=lambda x: x['created_at'])

            last_message_at_ts = None
            for msg in conversation_messages:
                ts = msg['created_at']
                msg['created_at'] = unix_to_iso(ts)
                if ts is not None:
                    if last_message_at_ts is None or ts > last_message_at_ts:
                        last_message_at_ts = ts

            thread_data = {
                'id': thread_id,
                'title': conversation.get('title', ''),
                'user_edited_title': False,
                'status': 'done',
                'model': conversation.get('default_model_slug'),
                'created_at': unix_to_iso(conversation.get('create_time')),
                'updated_at': unix_to_iso(conversation.get('update_time')),
                'last_message_at': unix_to_iso(last_message_at_ts),
            }
            
            all_threads.append(thread_data)
            all_messages.extend(conversation_messages)

        processing_time = time.time() - start_time
        monitor.record_metric("processing_time", processing_time)
        monitor.record_metric("thread_count", thread_count)
        monitor.record_metric("message_count", message_count)
        
        logger.info(f"Conversion complete. Processed {thread_count} threads and {message_count} messages in {processing_time:.2f} seconds.")
        return {"threads": all_threads, "messages": all_messages}

    except Exception as e:
        logger.error(f"Error during conversion: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def iso_to_unix(iso_str: Optional[str]) -> Optional[float]:
    """Converts an ISO 8601 string to a Unix timestamp."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return dt.timestamp()
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not convert ISO timestamp {iso_str}: {e}")
        return None

async def convert_file_with_timeout(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    filename: Optional[str] = None,
    start_time: float = None
):
    """Wrapper function to handle timeout for file conversion."""
    if start_time is None:
        start_time = time.time()
        
    try:
        # Handle chunked upload
        if filename and not file:
            logger.info(f"Processing chunked upload for {filename}")
            upload_dir = TEMP_DIR / filename
            if not upload_dir.exists():
                raise HTTPException(
                    status_code=400,
                    detail="No chunks found for this file"
                )
            
            # Combine chunks
            temp_file = TEMP_DIR / f"combined_{filename}"
            with open(temp_file, "wb") as outfile:
                chunk_files = sorted(upload_dir.glob("chunk_*"), key=lambda x: int(x.name.split("_")[1]))
                for chunk_file in chunk_files:
                    with open(chunk_file, "rb") as infile:
                        outfile.write(infile.read())
            
            # Clean up chunks
            shutil.rmtree(upload_dir)
            
            # Create a file-like object for processing
            file = UploadFile(
                filename=filename,
                file=open(temp_file, "rb"),
                content_type="application/json"
            )
        
        if not file:
            raise HTTPException(
                status_code=400,
                detail="No file provided"
            )
        
        # Validate file size
        file_size = 0
        chunk_size = 1024 * 1024  # 1MB chunks
        temp_file = TEMP_DIR / f"temp_{file.filename}"
        
        logger.info(f"Reading file: {file.filename}")
        with open(temp_file, "wb") as f:
            while chunk := await file.read(chunk_size):
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Maximum size is {MAX_FILE_SIZE} bytes"
                    )
                f.write(chunk)
        
        logger.info(f"File read complete. Size: {file_size} bytes")
        
        # Process the file
        try:
            logger.info("Starting JSON processing")
            with open(temp_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Extract messages and threads
            messages = []
            threads = []
            
            # Process conversations (data is a list of conversations)
            for conversation in data:
                if not isinstance(conversation, dict):
                    logger.warning(f"Skipping invalid conversation format: {type(conversation)}")
                    continue
                    
                # Create thread
                thread = {
                    'id': conversation.get('conversation_id') or conversation.get('id'),
                    'title': conversation.get('title', ''),
                    'user_edited_title': False,
                    'status': 'done',
                    'model': conversation.get('default_model_slug'),
                    'created_at': unix_to_iso(conversation.get('create_time')),
                    'updated_at': unix_to_iso(conversation.get('update_time')),
                    'last_message_at': None
                }
                
                # Process messages in the conversation
                conversation_messages = []
                mapping = conversation.get('mapping', {})
                
                for node_id, node in mapping.items():
                    if not isinstance(node, dict) or 'message' not in node:
                        continue
                        
                    message = node['message']
                    if not isinstance(message, dict):
                        continue
                        
                    author_info = message.get('author', {})
                    role = author_info.get('role') if isinstance(author_info, dict) else 'unknown'
                    content_text = extract_text_content(message.get('content'))
                    create_time = message.get('create_time')
                    model_slug = message.get('metadata', {}).get('model_slug') if isinstance(message.get('metadata'), dict) else None
                    status = message.get('status', 'unknown')
                    
                    if not message.get('id') or not role or create_time is None or not content_text:
                        continue
                        
                    msg = {
                        'id': message['id'],
                        'threadId': thread['id'],
                        'role': role,
                        'content': content_text,
                        'created_at': unix_to_iso(create_time),
                        'model': model_slug,
                        'status': status
                    }
                    conversation_messages.append(msg)
                    
                    # Update last_message_at - compare Unix timestamps
                    if create_time:
                        current_last = iso_to_unix(thread['last_message_at']) if thread['last_message_at'] else 0
                        if create_time > current_last:
                            thread['last_message_at'] = unix_to_iso(create_time)
                
                if conversation_messages:
                    threads.append(thread)
                    messages.extend(conversation_messages)
            
            logger.info(f"Processed {len(threads)} threads and {len(messages)} messages")
            
            # Create output file
            output_file = TEMP_DIR / f"converted_{file.filename}"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump({"messages": messages, "threads": threads}, f, indent=2)
            
            # Calculate processing time
            processing_time = time.time() - start_time
            logger.info(f"Conversion completed in {processing_time:.2f} seconds")
            
            # Clean up temporary files
            background_tasks.add_task(lambda: os.unlink(temp_file))
            background_tasks.add_task(lambda: os.unlink(output_file))
            
            return FileResponse(
                output_file,
                filename=f"converted_{file.filename}",
                media_type="application/json",
                headers={
                    "X-Processing-Time": f"{processing_time:.2f}",
                    "X-Thread-Count": str(len(threads)),
                    "X-Message-Count": str(len(messages))
                }
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail="Invalid JSON file"
            )
        except Exception as e:
            logger.error(f"Processing error: {str(e)}\n{traceback.format_exc()}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to process file: {str(e)}"
            )
            
    except asyncio.TimeoutError:
        logger.error("Operation timed out")
        raise HTTPException(
            status_code=504,
            detail="Operation timed out. Please try again with a smaller file or try later."
        )

@app.post("/api/convert")
async def convert_file(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    filename: Optional[str] = None
):
    global active_conversions
    start_time = time.time()
    
    try:
        logger.info(f"Starting conversion request. File: {filename or (file.filename if file else 'None')}")
        
        async with conversion_lock:
            if active_conversions >= MAX_CONCURRENT_CONVERSIONS:
                logger.warning("Server busy - too many concurrent conversions")
                raise HTTPException(
                    status_code=429,
                    detail="Server is busy. Please try again in a few seconds."
                )
            active_conversions += 1
            logger.info(f"Active conversions: {active_conversions}")
        
        # Use wait_for to implement timeout
        return await asyncio.wait_for(
            convert_file_with_timeout(request, background_tasks, file, filename, start_time),
            timeout=TIMEOUT
        )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}"
        )
    finally:
        async with conversion_lock:
            active_conversions -= 1
            logger.info(f"Active conversions after completion: {active_conversions}")
        
        # Clean up any remaining temporary files
        if 'temp_file' in locals():
            try:
                os.unlink(temp_file)
            except Exception as e:
                logger.error(f"Failed to clean up temp file: {str(e)}")

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "active_conversions": active_conversions
    }

@app.get("/api/stats")
async def get_stats():
    """Get conversion statistics."""
    return {
        "active_conversions": active_conversions,
        "max_concurrent_conversions": MAX_CONCURRENT_CONVERSIONS,
        "max_file_size": MAX_FILE_SIZE,
        "max_response_size": MAX_RESPONSE_SIZE
    }

@app.on_event("shutdown")
async def cleanup():
    # Clean up temporary directory
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)

# Add these exception handlers right after the app definition and before the routes
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc.detail)}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc)}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred"}
    )

# Note: For Vercel deployment, we don't need the uvicorn runner block here.
# Vercel will use the 'app' object directly. 
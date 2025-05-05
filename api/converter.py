import json
import os
from datetime import datetime, timezone
from fastapi import FastAPI, File, UploadFile, HTTPException, Request, BackgroundTasks, Form
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
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB (reduced from 50MB)
MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10MB
CHUNK_SIZE = 1024 * 1024  # 1MB chunks
MAX_CONCURRENT_CONVERSIONS = 3  # Reduced from 5
TEMP_DIR = Path(tempfile.gettempdir()) / "converter"
TEMP_DIR.mkdir(exist_ok=True)
TIMEOUT = 8  # 8 seconds (reduced from 50 to stay under 10s limit)

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

def process_timestamp(timestamp: Any) -> Optional[str]:
    """Convert various timestamp formats to ISO 8601 string."""
    if timestamp is None:
        return None
        
    try:
        # If it's already an ISO string, return it
        if isinstance(timestamp, str) and ('T' in timestamp or 'Z' in timestamp):
            return timestamp
            
        # If it's a Unix timestamp (float or int)
        if isinstance(timestamp, (int, float)):
            dt = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
            return dt.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            
        # If it's a datetime object
        if isinstance(timestamp, datetime):
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            return timestamp.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not convert timestamp {timestamp}: {e}")
        return None

def process_claude_message(message: dict, thread_id: str) -> Optional[dict]:
    """Process a message in Claude format."""
    if not isinstance(message, dict):
        return None
        
    role = message.get('role', 'unknown')
    content = message.get('content', '')
    create_time = message.get('created_at')
    
    if not message.get('uuid') or not role or not content:
        return None
        
    return {
        'id': message['uuid'],
        'threadId': thread_id,
        'role': role,
        'content': content,
        'created_at': process_timestamp(create_time),
        'model': None,  # Claude format doesn't include model info
        'status': 'done'
    }

def process_openai_message(message: dict, thread_id: str) -> Optional[dict]:
    """Process a message in OpenAI format."""
    if not isinstance(message, dict):
        return None
        
    author_info = message.get('author', {})
    role = author_info.get('role') if isinstance(author_info, dict) else 'unknown'
    content_text = extract_text_content(message.get('content'))
    create_time = message.get('create_time')
    model_slug = message.get('metadata', {}).get('model_slug') if isinstance(message.get('metadata'), dict) else None
    status = message.get('status', 'unknown')
    
    if not message.get('id') or not role or create_time is None or not content_text:
        return None
        
    return {
        'id': message['id'],
        'threadId': thread_id,
        'role': role,
        'content': content_text,
        'created_at': process_timestamp(create_time),
        'model': model_slug,
        'status': status
    }

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
                file=open(temp_file, "rb"),
                filename=filename,
                headers={"content-type": "application/json"}
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
            
            # Log input data structure
            logger.info(f"Input data type: {type(data)}")
            if isinstance(data, list):
                logger.info(f"Number of conversations in input: {len(data)}")
                if len(data) > 0:
                    logger.info(f"First conversation keys: {list(data[0].keys())}")
            elif isinstance(data, dict):
                logger.info(f"Top-level keys: {list(data.keys())}")
                if 'conversations' in data:
                    logger.info(f"Number of conversations: {len(data['conversations'])}")
            
            # Extract messages and threads
            messages = []
            threads = []
            
            # Handle both list and dict formats
            conversations = data if isinstance(data, list) else data.get('conversations', [])
            
            if not conversations:
                logger.error("No conversations found in input data")
                raise HTTPException(
                    status_code=400,
                    detail="No conversations found in input file"
                )
            
            logger.info(f"Processing {len(conversations)} conversations")
            
            # Process conversations
            for i, conversation in enumerate(conversations):
                if not isinstance(conversation, dict):
                    logger.warning(f"Skipping invalid conversation format at index {i}: {type(conversation)}")
                    continue
                
                logger.info(f"Processing conversation {i+1}/{len(conversations)}")
                logger.info(f"Conversation keys: {list(conversation.keys())}")
                
                # Determine if this is a Claude or OpenAI format
                is_claude_format = 'chat_messages' in conversation
                
                # Create thread
                thread = {
                    'id': conversation.get('conversation_id') or conversation.get('id') or conversation.get('uuid'),
                    'title': conversation.get('title') or conversation.get('name', ''),
                    'user_edited_title': False,
                    'status': 'done',
                    'model': conversation.get('default_model_slug'),
                    'created_at': process_timestamp(conversation.get('create_time') or conversation.get('created_at')),
                    'updated_at': process_timestamp(conversation.get('update_time') or conversation.get('updated_at')),
                    'last_message_at': None
                }
                
                # Process messages based on format
                conversation_messages = []
                
                if is_claude_format:
                    # Process Claude format
                    chat_messages = conversation.get('chat_messages', [])
                    logger.info(f"Processing {len(chat_messages)} Claude messages")
                    
                    for msg in chat_messages:
                        processed_msg = process_claude_message(msg, thread['id'])
                        if processed_msg:
                            conversation_messages.append(processed_msg)
                else:
                    # Process OpenAI format
                    mapping = conversation.get('mapping', {})
                    if not mapping:
                        logger.warning(f"No mapping found in conversation {i+1}")
                        continue
                    
                    logger.info(f"Processing {len(mapping)} OpenAI message nodes")
                    
                    for node_id, node in mapping.items():
                        if not isinstance(node, dict) or 'message' not in node:
                            logger.warning(f"Invalid node format in conversation {i+1}, node {node_id}")
                            continue
                            
                        processed_msg = process_openai_message(node['message'], thread['id'])
                        if processed_msg:
                            conversation_messages.append(processed_msg)
                
                if conversation_messages:
                    logger.info(f"Added {len(conversation_messages)} messages from conversation {i+1}")
                    # Sort messages by creation time
                    conversation_messages.sort(key=lambda x: x['created_at'])
                    # Update thread's last_message_at
                    if conversation_messages:
                        thread['last_message_at'] = conversation_messages[-1]['created_at']
                    threads.append(thread)
                    messages.extend(conversation_messages)
                else:
                    logger.warning(f"No valid messages found in conversation {i+1}")
            
            logger.info(f"Final processing results: {len(threads)} threads and {len(messages)} messages")
            
            if not threads or not messages:
                logger.error("No valid threads or messages found in the input file")
                raise HTTPException(
                    status_code=400,
                    detail="No valid conversations found in the input file"
                )
            
            # Create output file with descriptive name
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            source_format = "claude" if is_claude_format else "openai"
            original_name = Path(file.filename).stem
            output_filename = f"t3chat_export_{source_format}_{original_name}_{timestamp}.json"
            output_file = TEMP_DIR / output_filename
            
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
                filename=output_filename,
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="{output_filename}"',
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
    """Convert a file from OpenAI/Claude format to T3-Chat format."""
    global active_conversions
    start_time = time.time()
    
    try:
        logger.info(f"Starting conversion request. File: {filename or (file.filename if file else 'None')}")
        
        # Get filename from request body if not provided
        if not filename:
            try:
                body = await request.json()
                filename = body.get('filename')
                logger.info(f"Retrieved filename from request body: {filename}")
            except Exception as e:
                logger.error(f"Error reading request body: {str(e)}")
        
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

async def combine_chunks(filename: str) -> Path:
    """Combine all chunks into a single file."""
    try:
        chunks_dir = TEMP_DIR / filename
        if not chunks_dir.exists():
            logger.error(f"Chunks directory not found: {chunks_dir}")
            raise HTTPException(status_code=400, detail="Chunks directory not found")
            
        # Create the combined file
        combined_file = TEMP_DIR / f"combined_{filename}"
        logger.info(f"Creating combined file at: {combined_file}")
        
        with open(combined_file, "wb") as outfile:
            # Get all chunk files and sort them by index
            chunk_files = sorted(
                chunks_dir.glob("chunk_*"),
                key=lambda x: int(x.name.split("_")[1])
            )
            
            if not chunk_files:
                logger.error(f"No chunk files found in {chunks_dir}")
                raise HTTPException(status_code=400, detail="No chunk files found")
                
            logger.info(f"Found {len(chunk_files)} chunks to combine")
            
            # Combine chunks
            for chunk_file in chunk_files:
                logger.info(f"Processing chunk: {chunk_file}")
                with open(chunk_file, "rb") as infile:
                    outfile.write(infile.read())
                    
        logger.info(f"Successfully combined chunks into {combined_file}")
        return combined_file
        
    except Exception as e:
        logger.error(f"Error combining chunks: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to combine chunks: {str(e)}")

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

@app.post("/api/create-chunks")
async def create_chunks_directory(request: Request):
    """Create a directory for storing file chunks."""
    try:
        data = await request.json()
        filename = data.get('filename')
        if not filename:
            raise HTTPException(status_code=400, detail="Filename is required")
            
        chunks_dir = TEMP_DIR / filename
        chunks_dir.mkdir(exist_ok=True)
        
        return JSONResponse({"status": "success", "message": "Chunks directory created"})
    except Exception as e:
        logger.error(f"Error creating chunks directory: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload-chunk")
async def upload_chunk(
    file: UploadFile = File(...),
    filename: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...)
):
    """Handle uploading a single chunk of a file."""
    try:
        logger.info(f"Received chunk {chunk_index + 1} of {total_chunks} for file {filename}")
        
        # Validate inputs
        if not file:
            raise HTTPException(status_code=400, detail="No file provided")
        if not filename:
            raise HTTPException(status_code=400, detail="No filename provided")
        if chunk_index < 0:
            raise HTTPException(status_code=400, detail="Invalid chunk index")
        if total_chunks < 1:
            raise HTTPException(status_code=400, detail="Invalid total chunks")
            
        chunks_dir = TEMP_DIR / filename
        if not chunks_dir.exists():
            logger.error(f"Chunks directory not found: {chunks_dir}")
            raise HTTPException(status_code=400, detail="Chunks directory not found")
            
        chunk_path = chunks_dir / f"chunk_{chunk_index}"
        
        try:
            # Read chunk data
            content = await file.read()
            if not content:
                logger.error(f"Empty chunk received for {filename}, chunk {chunk_index}")
                raise HTTPException(status_code=400, detail="Empty chunk received")
            
            # Ensure the content is binary data
            if not isinstance(content, bytes):
                logger.error(f"Invalid chunk data type for {filename}, chunk {chunk_index}: {type(content)}")
                raise HTTPException(status_code=400, detail="Invalid chunk data format")
            
            # Save chunk
            with open(chunk_path, "wb") as f:
                f.write(content)
            logger.info(f"Successfully saved chunk {chunk_index + 1} of {total_chunks}")
            
        except Exception as e:
            logger.error(f"Error processing chunk {chunk_index + 1}: {str(e)}\n{traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to process chunk: {str(e)}")
            
        # If this is the last chunk, verify all chunks are present
        if chunk_index == total_chunks - 1:
            logger.info(f"Last chunk received, verifying all chunks for {filename}")
            missing_chunks = []
            for i in range(total_chunks):
                if not (chunks_dir / f"chunk_{i}").exists():
                    missing_chunks.append(i)
            
            if missing_chunks:
                logger.error(f"Missing chunks for {filename}: {missing_chunks}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing chunks: {', '.join(map(str, missing_chunks))}"
                )
            logger.info(f"All chunks verified for {filename}")
        
        return JSONResponse({
            "status": "success",
            "message": f"Chunk {chunk_index + 1} of {total_chunks} uploaded successfully"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during chunk upload: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

# Note: For Vercel deployment, we don't need the uvicorn runner block here.
# Vercel will use the 'app' object directly. 
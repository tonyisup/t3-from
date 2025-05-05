import ijson
import json
import os
from datetime import datetime, timezone
from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from collections import defaultdict
import io
import logging
import time
import traceback
from typing import Optional

# --- Constants ---
MAX_FILE_SIZE = 4 * 1024 * 1024  # 4MB (slightly under Vercel's 4.5MB limit)
MAX_RESPONSE_SIZE = 4 * 1024 * 1024  # 4MB (slightly under Vercel's 4.5MB limit)
CHUNK_SIZE = 8192  # 8KB chunks

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- FastAPI App ---
app = FastAPI(
    title="OpenAI Chat Export Converter",
    description="Converts OpenAI chat exports to T3-Chat format",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

def process_conversation_stream(file_stream: io.BytesIO, monitor: PerformanceMonitor) -> dict:
    """Processes the conversation data from a file stream using ijson and yields converted data."""
    all_threads = []
    all_messages = []
    processed_conversation_ids = set()
    message_count = 0
    thread_count = 0

    logger.info("Starting conversion process...")
    start_time = time.time()
    
    try:
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

# --- API Endpoints ---
@app.post("/api/convert")
async def convert_file(
    request: Request,
    file: UploadFile = File(...)
):
    """Receives OpenAI conversations.json, converts it, and returns the result."""
    monitor = PerformanceMonitor()
    monitor.start()

    if not file.filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a .json file.")

    logger.info(f"Received file: {file.filename}, Content-Type: {file.content_type}")

    try:
        # Check file size
        file_size = 0
        content_chunks = []
        
        # Read file in chunks to check size
        while chunk := await file.read(CHUNK_SIZE):
            file_size += len(chunk)
            if file_size > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum size is {MAX_FILE_SIZE/1024/1024}MB"
                )
            content_chunks.append(chunk)
        
        monitor.record_metric("file_size", file_size)
        
        # Combine chunks into a single BytesIO object
        file_stream = io.BytesIO(b''.join(content_chunks))
        
        logger.info(f"File read into memory ({file_size} bytes). Starting ijson processing...")
        
        converted_data = process_conversation_stream(file_stream, monitor)
        
        # Convert the result back to JSON string
        output_json_string = json.dumps(converted_data, indent=2)
        output_bytes = output_json_string.encode('utf-8')
        
        # Check response size
        if len(output_bytes) > MAX_RESPONSE_SIZE:
            raise HTTPException(
                status_code=413,
                detail="Converted file is too large to return. Please try with a smaller input file."
            )

        monitor.record_metric("output_size", len(output_bytes))
        logger.info(f"Conversion metrics: {monitor.get_metrics()}")

        # Return as a downloadable file
        return StreamingResponse(
            io.BytesIO(output_bytes),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=openai_converted_threads.json",
                "X-Processing-Time": str(monitor.get_elapsed_time()),
                "X-Thread-Count": str(monitor.metrics.get("thread_count", 0)),
                "X-Message-Count": str(monitor.metrics.get("message_count", 0))
            }
        )

    except (ijson.JSONError, json.JSONDecodeError) as e:
        logger.error(f"JSON Processing Error: {e}")
        raise HTTPException(status_code=400, detail=f"Error processing JSON file: {e}")
    except HTTPException as e:
        # Re-raise HTTP exceptions
        raise e
    except Exception as e:
        logger.error(f"An unexpected error occurred during conversion: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred during conversion.")
    finally:
        await file.close()
        logger.info(f"Closed file: {file.filename}")

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0"
    }

# Note: For Vercel deployment, we don't need the uvicorn runner block here.
# Vercel will use the 'app' object directly. 
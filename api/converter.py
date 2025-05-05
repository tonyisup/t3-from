import ijson
import json
import os
from datetime import datetime, timezone
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
from collections import defaultdict
import io
import logging

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FastAPI App ---
app = FastAPI()

# --- Helper Functions (Adapted from previous script) ---
def unix_to_iso(unix_timestamp):
    # ... (Keep the existing unix_to_iso function as modified before)
    """Converts a Unix timestamp (float or Decimal) to an ISO 8601 string in UTC."""
    if unix_timestamp is None:
        return None
    try:
        # Explicitly convert to float to handle potential Decimal types from ijson
        float_timestamp = float(unix_timestamp)
        dt_object = datetime.fromtimestamp(float_timestamp, tz=timezone.utc)
        return dt_object.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    except (TypeError, ValueError) as e:
        logger.warning(f"Could not convert timestamp {unix_timestamp}: {e}")
        return datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

def extract_text_content(content_obj):
    # ... (Keep the existing extract_text_content function)
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

def process_conversation_stream(file_stream):
    """Processes the conversation data from a file stream using ijson and yields converted data."""
    all_threads = []
    all_messages = []
    processed_conversation_ids = set()

    logger.info("Starting conversion process...")
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

        logger.debug(f"Processing conversation: {thread_id} ({conversation.get('title', 'No Title')[:50]}...)")

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
                 continue # Skip incomplete or empty messages

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
        logger.debug(f"Finished processing thread {thread_id}")

    logger.info(f"Conversion complete. Found {len(all_threads)} threads and {len(all_messages)} messages.")
    return {"threads": all_threads, "messages": all_messages}

# --- API Endpoint ---
@app.post("/api/convert")
async def convert_file(file: UploadFile = File(...)):
    """Receives OpenAI conversations.json, converts it, and returns the result."""
    if not file.filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a .json file.")

    logger.info(f"Received file: {file.filename}, Content-Type: {file.content_type}")

    try:
        # Process the file stream directly
        # We need to wrap the async file reader for ijson
        # A simple way is to read it all into memory if files aren't excessively large for serverless RAM
        # For true streaming with ijson on async FastAPI, more complex async iteration is needed.
        # Let's start with reading into BytesIO for simplicity, assuming Vercel limits are sufficient.
        
        content_bytes = await file.read()
        file_stream = io.BytesIO(content_bytes)
        
        logger.info(f"File read into memory ({len(content_bytes)} bytes). Starting ijson processing...")
        
        converted_data = process_conversation_stream(file_stream)
        
        # Convert the result back to JSON string
        output_json_string = json.dumps(converted_data, indent=2)
        output_bytes = output_json_string.encode('utf-8')

        logger.info("Conversion successful. Preparing download response.")

        # Return as a downloadable file
        return StreamingResponse(
            io.BytesIO(output_bytes),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=openai_converted_threads.json"}
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
    return {"status": "ok"}

# Note: For Vercel deployment, we don't need the uvicorn runner block here.
# Vercel will use the 'app' object directly. 
# OpenAI/Claude Chat Export Converter

A web-based tool for converting OpenAI and Claude chat exports to the T3-Chat format. This tool supports both OpenAI's chat history exports and Claude's conversation exports, automatically detecting the format and handling large files through chunked uploads.

## 🌟 Features

- **Multi-Format Support**
  - Automatically detects and processes both OpenAI and Claude export formats
  - Handles different timestamp formats and message structures
  - Preserves all message metadata and relationships

- **Large File Support**
  - Processes files larger than 10MB through automatic chunked uploads
  - Progress tracking with visual feedback
  - Efficient memory usage through streaming processing

- **User-Friendly Interface**
  - Simple drag-and-drop or file selection
  - Real-time progress updates
  - Descriptive output filenames with source format and timestamp
  - Clear error messages and status updates

- **Robust Error Handling**
  - Comprehensive validation of input files
  - Detailed error messages for troubleshooting
  - Automatic cleanup of temporary files
  - Rate limiting to prevent server overload

## 🚀 Usage

1. **Prepare Your Export File**
   - For OpenAI: Export your chat history from ChatGPT
   - For Claude: Export your conversations from Claude
   - Ensure the file is in JSON format

2. **Convert Your File**
   - Visit the converter website
   - Click "Choose File" and select your export file
   - Wait for the conversion to complete
   - Download the converted file

3. **Using the Converted File**
   - The output will be in T3-Chat format
   - Filename format: `t3chat_export_[source]_[original_name]_[timestamp].json`
   - Contains all messages, threads, and metadata

## 📋 Input Formats

### OpenAI Format
```json
{
  "conversations": [
    {
      "id": "thread_id",
      "title": "Conversation Title",
      "create_time": 1234567890,
      "mapping": {
        "message_id": {
          "message": {
            "id": "message_id",
            "author": { "role": "user" },
            "content": { "parts": ["message content"] },
            "create_time": 1234567890
          }
        }
      }
    }
  ]
}
```

### Claude Format
```json
[
  {
    "uuid": "thread_id",
    "name": "Conversation Title",
    "created_at": "2024-03-20T12:00:00Z",
    "chat_messages": [
      {
        "uuid": "message_id",
        "role": "user",
        "content": "message content",
        "created_at": "2024-03-20T12:00:00Z"
      }
    ]
  }
]
```

## 📤 Output Format

The converter outputs a standardized T3-Chat format JSON file with the following structure:

```json
{
  "messages": [
    {
      "id": "msg_123abc",
      "threadId": "thread_456def",
      "role": "user",
      "content": "Hello, how can you help me today?",
      "created_at": "2024-03-20T12:00:00.000Z",
      "model": "gpt-4",
      "status": "done"
    },
    {
      "id": "msg_789ghi",
      "threadId": "thread_456def",
      "role": "assistant",
      "content": "I'm here to help! What would you like to know?",
      "created_at": "2024-03-20T12:00:05.000Z",
      "model": "gpt-4",
      "status": "done"
    }
  ],
  "threads": [
    {
      "id": "thread_456def",
      "title": "General Conversation",
      "user_edited_title": false,
      "status": "done",
      "model": "gpt-4",
      "created_at": "2024-03-20T12:00:00.000Z",
      "updated_at": "2024-03-20T12:00:05.000Z",
      "last_message_at": "2024-03-20T12:00:05.000Z"
    }
  ]
}
```

### Output Fields

#### Messages
- `id`: Unique message identifier
- `threadId`: ID of the thread this message belongs to
- `role`: Message role ("user" or "assistant")
- `content`: The message content
- `created_at`: ISO 8601 timestamp of message creation
- `model`: The model used (if available)
- `status`: Message status (typically "done")

#### Threads
- `id`: Unique thread identifier
- `title`: Thread title
- `user_edited_title`: Whether the title was manually edited
- `status`: Thread status (typically "done")
- `model`: Default model for the thread
- `created_at`: ISO 8601 timestamp of thread creation
- `updated_at`: ISO 8601 timestamp of last update
- `last_message_at`: ISO 8601 timestamp of the last message

## ⚙️ Technical Details

### API Endpoints

- `POST /api/convert`: Main conversion endpoint
- `POST /api/create-chunks`: Creates directory for chunked uploads
- `POST /api/upload-chunk`: Handles individual chunk uploads
- `GET /api/health`: Health check endpoint
- `GET /api/stats`: Server statistics

### Limitations

- Maximum file size: 50MB
- Maximum chunk size: 5MB
- Processing timeout: 8 seconds
- Maximum concurrent conversions: 3

### Error Handling

The converter includes comprehensive error handling for:
- Invalid file formats
- Missing or corrupt data
- Timestamp conversion issues
- File size limits
- Server resource constraints

## 🛠️ Development

### Prerequisites

- Python 3.9+
- FastAPI
- Vercel CLI (for deployment)

### Local Development

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the development server:
   ```bash
   uvicorn api.converter:app --reload
   ```

### Deployment

The application is configured for deployment on Vercel:
- Python runtime: 3.9
- Maximum Lambda size: 50MB
- Maximum duration: 60 seconds
- Memory: 1024MB

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 💬 Support

If you encounter any issues or have questions, please:
1. Check the error message for specific details
2. Review the input format requirements
3. Open an issue on GitHub with:
   - The error message
   - A sample of your input file (with sensitive data removed)
   - Steps to reproduce the issue 
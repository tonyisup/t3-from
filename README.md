# OpenAI/Claude Chat Export Converter

A web application that converts OpenAI and Claude chat exports to the T3-Chat format. This tool helps you migrate your chat history from either OpenAI's or Claude's export format to a standardized format.

## Features

- Supports both OpenAI and Claude export formats
- Automatic format detection
- Handles large files with chunked uploads
- Progress tracking during conversion
- Automatic retry on failure
- Supports files up to 50MB
- Preserves message metadata, timestamps, and thread relationships
- Clean, modern UI with error handling
- Descriptive output filenames with source format and timestamp

## Usage

1. Visit the web application
2. Click "Choose File" and select your export file:
   - For OpenAI: `conversations.json`
   - For Claude: Your exported JSON file
3. Click "Convert File"
4. Wait for the conversion to complete
5. Click the download link to save your converted file

The converted file will be named in the format: `t3chat_export_[source]_[original_name]_[timestamp].json`

## Technical Details

### Supported Input Formats

#### OpenAI Format
```json
{
  "conversations": [
    {
      "id": "string",
      "title": "string",
      "mapping": {
        "node_id": {
          "message": {
            "id": "string",
            "author": { "role": "string" },
            "content": { "parts": ["string"] },
            "create_time": float,
            "metadata": { "model_slug": "string" }
          }
        }
      }
    }
  ]
}
```

#### Claude Format
```json
[
  {
    "uuid": "string",
    "name": "string",
    "created_at": "ISO-8601 string",
    "chat_messages": [
      {
        "uuid": "string",
        "role": "string",
        "content": "string",
        "created_at": "ISO-8601 string"
      }
    ]
  }
]
```

### Output Format

The converter outputs a JSON file in the T3-Chat format:

```json
{
  "messages": [
    {
      "id": "string",
      "threadId": "string",
      "role": "string",
      "content": "string",
      "created_at": "ISO-8601 timestamp",
      "model": "string",
      "status": "string"
    }
  ],
  "threads": [
    {
      "id": "string",
      "title": "string",
      "user_edited_title": boolean,
      "status": "string",
      "model": "string",
      "created_at": "ISO-8601 timestamp",
      "updated_at": "ISO-8601 timestamp",
      "last_message_at": "ISO-8601 timestamp"
    }
  ]
}
```

### Limitations

- Maximum file size: 50MB
- Maximum processing time: 60 seconds
- Maximum concurrent conversions: 5

### API Endpoints

- `POST /api/convert`: Main conversion endpoint
- `GET /api/health`: Health check endpoint
- `GET /api/stats`: Statistics endpoint

## Development

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

The application is configured for deployment on Vercel. The `vercel.json` file includes:

- Python runtime configuration
- Static file serving
- CORS headers
- Function size and duration limits

## Error Handling

The application includes comprehensive error handling for:

- Invalid file formats
- File size limits
- Processing timeouts
- Server errors
- Network issues
- Invalid timestamps
- Missing required fields

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - feel free to use this project for any purpose.

## Support

If you encounter any issues or have questions, please open an issue on the repository. 
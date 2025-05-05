# OpenAI Chat Export Converter

A web application that converts OpenAI and Claude chat exports to the T3-Chat format. This tool helps you migrate your chat history from OpenAI's export format to a more standardized format.

## Features

- Converts OpenAI/Claude chat exports to T3-Chat format
- Handles large files with chunked uploads
- Progress tracking during conversion
- Automatic retry on failure
- Supports files up to 50MB
- Preserves message metadata, timestamps, and thread relationships
- Clean, modern UI with error handling

## Usage

1. Visit the web application
2. Click "Choose File" and select your `conversations.json` file from your OpenAI/Claude export
3. Click "Convert File"
4. Wait for the conversion to complete
5. Click the download link to save your converted file

## Technical Details

### File Format

The converter expects a JSON file in the OpenAI/Claude export format and outputs a JSON file in the T3-Chat format with the following structure:

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

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - feel free to use this project for any purpose.

## Support

If you encounter any issues or have questions, please open an issue on the repository. 
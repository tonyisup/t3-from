# OpenAI Chat Export Converter

A web-based tool that converts OpenAI chat export files (`conversations.json`) to the T3-Chat format. This converter supports both OpenAI and Claude conversation formats.

## 🚀 Features

- Web-based interface for easy file conversion
- Supports OpenAI chat export format
- Supports Claude conversation format
- Converts timestamps to ISO format
- Preserves message metadata and threading
- Handles both single and multiple conversation exports
- Real-time progress indication
- Automatic file download after conversion

## 🛠️ Technical Stack

- HTML5
- CSS3
- JavaScript (Vanilla)
- Python (Backend conversion support)

## 📦 Project Structure

```
.
├── index.html          # Main web interface
├── style.css          # Styling for the web interface
├── script.js          # Frontend JavaScript logic
├── converter.js       # Core conversion logic
└── converter.py       # Python-based conversion support
```

## 🚀 Getting Started

1. Clone this repository
2. Open `index.html` in your web browser
3. Upload your `conversations.json` file from OpenAI export
4. Click "Convert File"
5. Download the converted file when ready

## 💻 Usage

1. Export your conversations from OpenAI:
   - Go to your OpenAI account settings
   - Navigate to the Data Export section
   - Request and download your data export

2. Use the converter:
   - Open the web interface
   - Click "Choose conversations.json"
   - Select your exported file
   - Click "Convert File"
   - Wait for the conversion to complete
   - Click the download link to save your converted file

## 🔧 Development

The project consists of two main components:

1. **Frontend (Web Interface)**
   - `index.html`: Main user interface
   - `style.css`: Styling and layout
   - `script.js`: Frontend logic and UI interactions
   - `converter.js`: Core conversion logic

## 📝 Notes

- The converter handles both single conversation and multiple conversation exports
- All timestamps are converted to ISO 8601 format
- Message threading and metadata are preserved
- The tool supports both OpenAI and Claude conversation formats

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is open source and available under the MIT License.

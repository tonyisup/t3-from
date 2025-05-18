import json
import sys
from typing import Dict, List, Set, Optional
from pathlib import Path
from datetime import datetime
import openai
from collections import defaultdict
import re

def load_json_file(file_path: str) -> Dict:
    """Load and parse a JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading file {file_path}: {e}")
        sys.exit(1)

def analyze_thread_content(thread: Dict) -> Dict:
    """Analyze a thread's content for potential issues."""
    analysis = {
        "title_length": len(thread.get("title", "")),
        "has_special_chars": bool(re.search(r'[^\w\s-]', thread.get("title", ""))),
        "status": thread.get("status"),
        "model": thread.get("model"),
        "created_at": thread.get("created_at"),
        "updated_at": thread.get("updated_at"),
        "last_message_at": thread.get("last_message_at")
    }
    return analysis

def analyze_messages(messages: List[Dict], thread_id: str) -> Dict:
    """Analyze messages for a specific thread."""
    if not messages:
        return {"message_count": 0, "has_errors": False, "error_types": []}
    
    error_types = set()
    for msg in messages:
        if msg.get("status") == "failed":
            error_types.add("failed_status")
        if not msg.get("content"):
            error_types.add("empty_content")
        if msg.get("role") not in ["user", "assistant", "system"]:
            error_types.add("invalid_role")
    
    return {
        "message_count": len(messages),
        "has_errors": bool(error_types),
        "error_types": list(error_types)
    }

def compare_messages(source_messages: List[Dict], isolated_messages: List[Dict], thread_id: str) -> Dict:
    """Compare messages between source and isolated files."""
    source_msg_ids = {msg.get("id") for msg in source_messages}
    isolated_msg_ids = {msg.get("id") for msg in isolated_messages}
    
    missing_in_isolated = source_msg_ids - isolated_msg_ids
    extra_in_isolated = isolated_msg_ids - source_msg_ids
    
    return {
        "source_message_count": len(source_messages),
        "isolated_message_count": len(isolated_messages),
        "missing_in_isolated": len(missing_in_isolated),
        "extra_in_isolated": len(extra_in_isolated),
        "missing_message_ids": list(missing_in_isolated),
        "extra_message_ids": list(extra_in_isolated)
    }

def generate_ai_analysis(thread_data: Dict, messages_data: Dict, comparison_data: Dict) -> str:
    """Use OpenAI API to analyze potential issues."""
    try:
        # Prepare the prompt
        prompt = f"""Analyze this thread data and suggest potential reasons why messages might be missing:

Thread Info:
- Title: {thread_data.get('title', 'N/A')}
- Status: {thread_data.get('status', 'N/A')}
- Model: {thread_data.get('model', 'N/A')}
- Created: {thread_data.get('created_at', 'N/A')}
- Last Message: {thread_data.get('last_message_at', 'N/A')}

Message Analysis:
- Source Message Count: {messages_data.get('source_message_count', 0)}
- Isolated Message Count: {messages_data.get('isolated_message_count', 0)}
- Missing in Isolated: {messages_data.get('missing_in_isolated', 0)}
- Extra in Isolated: {messages_data.get('extra_in_isolated', 0)}

Comparison Analysis:
- Missing Message IDs: {', '.join(messages_data.get('missing_message_ids', []))}
- Extra Message IDs: {', '.join(messages_data.get('extra_message_ids', []))}

Please provide a brief analysis of potential issues and recommendations."""
        
        # Call OpenAI API
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant analyzing chat thread data for potential issues."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200
        )
        
        return response.choices[0].message.content
    except Exception as e:
        return f"AI analysis failed: {str(e)}"

def generate_summary(thread_analyses: List[Dict]) -> str:
    """Generate a summary of all thread analyses."""
    total_threads = len(thread_analyses)
    total_missing_messages = sum(analysis["comparison"]["missing_in_isolated"] for analysis in thread_analyses)
    total_extra_messages = sum(analysis["comparison"]["extra_in_isolated"] for analysis in thread_analyses)
    threads_with_errors = sum(1 for analysis in thread_analyses if analysis["source_analysis"]["has_errors"])
    
    # Collect unique error types and their counts
    error_type_counts = defaultdict(int)
    for analysis in thread_analyses:
        for error_type in analysis["source_analysis"]["error_types"]:
            error_type_counts[error_type] += 1
    
    # Collect model distribution
    model_distribution = defaultdict(int)
    for analysis in thread_analyses:
        model = analysis["thread_analysis"].get("model", "unknown")
        model_distribution[model] += 1
    
    summary = [
        "\nSummary Report",
        "=============",
        f"\nTotal Threads Analyzed: {total_threads}",
        f"Total Missing Messages: {total_missing_messages}",
        f"Total Extra Messages: {total_extra_messages}",
        f"Threads with Errors: {threads_with_errors}",
        f"Error Rate: {(threads_with_errors/total_threads)*100:.1f}%",
        "\nError Type Distribution:",
    ]
    
    # Add error type counts, sorted by count (descending)
    for error_type, count in sorted(error_type_counts.items(), key=lambda x: x[1], reverse=True):
        percentage = (count / total_threads) * 100
        summary.append(f"- {error_type}: {count} occurrences ({percentage:.1f}% of threads)")
    
    summary.append("\nModel Distribution:")
    for model, count in sorted(model_distribution.items()):
        summary.append(f"- {model}: {count} threads ({(count/total_threads)*100:.1f}%)")
    
    return "\n".join(summary)

def analyze_isolated_files(source_file: str, isolated_source_file: str, target_file: str, openai_api_key: Optional[str] = None) -> None:
    """Analyze the isolated files to identify potential issues."""
    # Load the files
    source_data = load_json_file(source_file)
    isolated_source_data = load_json_file(isolated_source_file)
    target_data = load_json_file(target_file)
    
    # Initialize OpenAI if API key is provided
    if openai_api_key:
        openai.api_key = openai_api_key
    
    # Create analysis report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = f"thread_analysis_{timestamp}.txt"
    
    # Store all analyses for summary
    thread_analyses = []
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("Thread Analysis Report\n")
        f.write("=====================\n\n")
        
        # Analyze each thread
        for thread in isolated_source_data["threads"]:
            thread_id = thread["id"]
            f.write(f"\nThread ID: {thread_id}\n")
            f.write("-" * 50 + "\n")
            
            # Get thread analysis
            thread_analysis = analyze_thread_content(thread)
            f.write("\nThread Analysis:\n")
            for key, value in thread_analysis.items():
                f.write(f"- {key}: {value}\n")
            
            # Get messages for this thread
            source_messages = [m for m in source_data.get("messages", []) if m["threadId"] == thread_id]
            isolated_messages = [m for m in isolated_source_data.get("messages", []) if m["threadId"] == thread_id]
            target_messages = [m for m in target_data.get("messages", []) if m["threadId"] == thread_id]
            
            # Compare messages between source and isolated
            comparison_analysis = compare_messages(source_messages, isolated_messages, thread_id)
            
            f.write("\nMessage Comparison Analysis:\n")
            f.write("Source vs Isolated:\n")
            for key, value in comparison_analysis.items():
                if key not in ["missing_message_ids", "extra_message_ids"]:
                    f.write(f"- {key}: {value}\n")
            
            if comparison_analysis["missing_message_ids"]:
                f.write("\nMissing Message IDs in Isolated:\n")
                for msg_id in comparison_analysis["missing_message_ids"]:
                    f.write(f"- {msg_id}\n")
            
            if comparison_analysis["extra_message_ids"]:
                f.write("\nExtra Message IDs in Isolated:\n")
                for msg_id in comparison_analysis["extra_message_ids"]:
                    f.write(f"- {msg_id}\n")
            
            # Analyze messages
            source_msg_analysis = analyze_messages(source_messages, thread_id)
            isolated_msg_analysis = analyze_messages(isolated_messages, thread_id)
            target_msg_analysis = analyze_messages(target_messages, thread_id)
            
            f.write("\nMessage Analysis:\n")
            f.write("Source Messages:\n")
            for key, value in source_msg_analysis.items():
                f.write(f"- {key}: {value}\n")
            
            f.write("\nIsolated Messages:\n")
            for key, value in isolated_msg_analysis.items():
                f.write(f"- {key}: {value}\n")
            
            f.write("\nTarget Messages:\n")
            for key, value in target_msg_analysis.items():
                f.write(f"- {key}: {value}\n")
            
            # Generate AI analysis if API key is provided
            if openai_api_key:
                f.write("\nAI Analysis:\n")
                ai_analysis = generate_ai_analysis(thread, comparison_analysis, comparison_analysis)
                f.write(ai_analysis + "\n")
            
            f.write("\n" + "=" * 50 + "\n")
            
            # Store analysis for summary
            thread_analyses.append({
                "thread_analysis": thread_analysis,
                "source_analysis": source_msg_analysis,
                "comparison": comparison_analysis
            })
        
        # Add summary section
        f.write(generate_summary(thread_analyses))
    
    print(f"\nAnalysis complete! Report written to: {report_file}")

def main():
    if len(sys.argv) < 4:
        print("Usage: python analyze_missing_threads.py <source_file> <isolated_source_file> <target_file> [openai_api_key]")
        sys.exit(1)
    
    source_file = sys.argv[1]
    isolated_source_file = sys.argv[2]
    target_file = sys.argv[3]
    openai_api_key = sys.argv[4] if len(sys.argv) > 4 else None
    
    # Validate file existence
    if not Path(source_file).exists():
        print(f"Error: Source file '{source_file}' does not exist")
        sys.exit(1)
    if not Path(isolated_source_file).exists():
        print(f"Error: Isolated source file '{isolated_source_file}' does not exist")
        sys.exit(1)
    if not Path(target_file).exists():
        print(f"Error: Target file '{target_file}' does not exist")
        sys.exit(1)
    
    analyze_isolated_files(source_file, isolated_source_file, target_file, openai_api_key)

if __name__ == "__main__":
    main() 
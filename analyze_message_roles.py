import json
import sys
from typing import Dict, List
from pathlib import Path
from datetime import datetime
from collections import defaultdict

def load_json_file(file_path: str) -> Dict:
    """Load and parse a JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading file {file_path}: {e}")
        sys.exit(1)

def analyze_message_roles(messages: List[Dict]) -> Dict:
    """Analyze message roles and their counts."""
    role_counts = defaultdict(int)
    role_thread_counts = defaultdict(set)  # Track unique threads per role
    
    for message in messages:
        role = message.get("role", "unknown")
        thread_id = message.get("threadId")
        
        role_counts[role] += 1
        if thread_id:
            role_thread_counts[role].add(thread_id)
    
    return {
        "role_counts": dict(role_counts),
        "role_thread_counts": {role: len(threads) for role, threads in role_thread_counts.items()}
    }

def generate_report(analysis: Dict, total_messages: int, total_threads: int) -> str:
    """Generate a formatted report of the analysis."""
    report = [
        "Message Role Analysis Report",
        "========================",
        f"\nTotal Messages: {total_messages}",
        f"Total Threads: {total_threads}",
        "\nMessage Counts by Role:",
    ]
    
    # Sort roles by count (descending)
    sorted_roles = sorted(
        analysis["role_counts"].items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    for role, count in sorted_roles:
        percentage = (count / total_messages) * 100
        thread_count = analysis["role_thread_counts"][role]
        thread_percentage = (thread_count / total_threads) * 100
        
        report.extend([
            f"\n{role.upper()}:",
            f"- Message Count: {count} ({percentage:.1f}% of total messages)",
            f"- Thread Count: {thread_count} ({thread_percentage:.1f}% of total threads)",
            f"- Average Messages per Thread: {count/thread_count:.1f}" if thread_count > 0 else "- No threads found"
        ])
    
    return "\n".join(report)

def main():
    if len(sys.argv) != 2:
        print("Usage: python analyze_message_roles.py <source_file>")
        sys.exit(1)
    
    source_file = sys.argv[1]
    
    # Validate file existence
    if not Path(source_file).exists():
        print(f"Error: Source file '{source_file}' does not exist")
        sys.exit(1)
    
    # Load and analyze the file
    data = load_json_file(source_file)
    
    if "messages" not in data:
        print("Error: No messages found in the source file")
        sys.exit(1)
    
    # Get total counts
    total_messages = len(data["messages"])
    total_threads = len(data.get("threads", []))
    
    # Analyze message roles
    analysis = analyze_message_roles(data["messages"])
    
    # Generate and write report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = f"message_role_analysis_{timestamp}.txt"
    
    report = generate_report(analysis, total_messages, total_threads)
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\nAnalysis complete! Report written to: {report_file}")
    
    # Also print to console
    print("\n" + report)

if __name__ == "__main__":
    main() 
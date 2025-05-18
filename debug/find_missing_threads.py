import json
import sys
from typing import Set, Dict, List
from pathlib import Path
from datetime import datetime

def load_json_file(file_path: str) -> Dict:
    """Load and parse a JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading file {file_path}: {e}")
        sys.exit(1)

def get_source_thread_ids(source_data: Dict) -> Set[str]:
    """Extract thread IDs from source file, excluding threads with tool messages."""
    if 'threads' not in source_data:
        print("Error: 'threads' not found in source file")
        sys.exit(1)
    
    # Get all messages with role "tool"
    tool_message_thread_ids = {
        message['threadId'] 
        for message in source_data.get('messages', [])
        if message.get('role') == 'tool'
    }
    
    # Return thread IDs that don't have any tool messages
    return {
        thread['id'] 
        for thread in source_data['threads']
        if thread['id'] not in tool_message_thread_ids
    }

def get_target_thread_ids(target_data: Dict) -> Set[str]:
    """Extract thread IDs from messages in target file, excluding threads with tool messages."""
    if 'messages' not in target_data:
        print("Error: 'messages' not found in target file")
        sys.exit(1)
    
    # Get all messages with role "tool"
    tool_message_thread_ids = {
        message['threadId'] 
        for message in target_data['messages']
        if message.get('role') == 'tool'
    }
    
    # Return thread IDs that don't have any tool messages
    return {
        message['threadId'] 
        for message in target_data['messages']
        if message['threadId'] not in tool_message_thread_ids
    }

def find_missing_threads(source_file: str, target_file: str) -> List[str]:
    """Find thread IDs that are in source but missing in target messages."""
    # Load both files
    source_data = load_json_file(source_file)
    target_data = load_json_file(target_file)
    
    # Get thread IDs from both files (excluding threads with tool messages)
    source_thread_ids = get_source_thread_ids(source_data)
    target_thread_ids = get_target_thread_ids(target_data)
    
    # Find missing thread IDs
    missing_threads = list(source_thread_ids - target_thread_ids)
    missing_threads.sort()  # Sort for consistent output
    
    return missing_threads

def write_missing_threads_to_file(missing_threads: List[str], source_file: str, target_file: str) -> str:
    """Write missing thread IDs to a file and return the output file path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"missing_threads_{timestamp}.txt"
    
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"Missing Thread IDs Report\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Source File: {source_file}\n")
            f.write(f"Target File: {target_file}\n")
            f.write(f"Total Missing Threads: {len(missing_threads)}\n\n")
            
            for thread_id in missing_threads:
                f.write(f"{thread_id}\n")
        
        return output_file
    except Exception as e:
        print(f"Error writing to file {output_file}: {e}")
        sys.exit(1)

def create_isolated_files(source_file: str, target_file: str, missing_threads: List[str]) -> tuple[str, str]:
    """Create isolated JSON files containing only the missing threads and their messages."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    source_isolated = f"source_isolated_{timestamp}.json"
    target_isolated = f"target_isolated_{timestamp}.json"
    
    try:
        # Load the full files
        source_data = load_json_file(source_file)
        target_data = load_json_file(target_file)
        
        # Create isolated source file with both threads and messages
        source_isolated_data = {
            "threads": [
                thread for thread in source_data["threads"]
                if thread["id"] in missing_threads
            ],
            "messages": [
                message for message in source_data.get("messages", [])
                if message["threadId"] in missing_threads and message.get("role") != "tool"
            ]
        }
        
        # Create isolated target file with both threads and messages
        target_isolated_data = {
            "threads": [
                thread for thread in target_data.get("threads", [])
                if thread["id"] in missing_threads
            ],
            "messages": [
                message for message in target_data["messages"]
                if message["threadId"] in missing_threads and message.get("role") != "tool"
            ]
        }
        
        # Write isolated files
        with open(source_isolated, 'w', encoding='utf-8') as f:
            json.dump(source_isolated_data, f, indent=2)
        
        with open(target_isolated, 'w', encoding='utf-8') as f:
            json.dump(target_isolated_data, f, indent=2)
        
        return source_isolated, target_isolated
    
    except Exception as e:
        print(f"Error creating isolated files: {e}")
        sys.exit(1)

def main():
    if len(sys.argv) != 3:
        print("Usage: python find_missing_threads.py <source_file> <target_file>")
        sys.exit(1)
    
    source_file = sys.argv[1]
    target_file = sys.argv[2]
    
    # Validate file existence
    if not Path(source_file).exists():
        print(f"Error: Source file '{source_file}' does not exist")
        sys.exit(1)
    if not Path(target_file).exists():
        print(f"Error: Target file '{target_file}' does not exist")
        sys.exit(1)
    
    # Find missing threads
    missing_threads = find_missing_threads(source_file, target_file)
    
    # Print results to console
    if missing_threads:
        print(f"\nFound {len(missing_threads)} missing thread IDs:")
        for thread_id in missing_threads:
            print(f"- {thread_id}")
    else:
        print("\nNo missing thread IDs found.")
    
    # Write results to text file
    output_file = write_missing_threads_to_file(missing_threads, source_file, target_file)
    print(f"\nResults have been written to: {output_file}")
    
    # Create isolated files
    if missing_threads:
        source_isolated, target_isolated = create_isolated_files(source_file, target_file, missing_threads)
        print(f"\nIsolated files created:")
        print(f"- Source isolated: {source_isolated}")
        print(f"- Target isolated: {target_isolated}")

if __name__ == "__main__":
    main() 
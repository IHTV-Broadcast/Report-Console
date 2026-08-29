import os
import json
import shutil
from pathlib import Path

REPORTS_DIR = Path(__file__).parent / 'reports'

def cleanup_reports():
    """
    Clean up the reports directory by:
    1. Keeping only the main reports.json and Excel files
    2. Removing all individual JSON report files
    3. Removing any temporary files (like ~$ files)
    """
    print("Starting cleanup of reports directory...")
    
    # Ensure reports directory exists
    if not REPORTS_DIR.exists():
        print("Reports directory does not exist. Nothing to clean up.")
        return
    
    # Files to keep
    files_to_keep = {'reports.json', 'reports_2025_06.xlsx'}
    
    # Track what we're doing
    deleted_files = []
    kept_files = []
    
    # Process each file in the directory
    for file_path in REPORTS_DIR.glob('*'):
        file_name = file_path.name
        
        # Skip directories
        if file_path.is_dir():
            continue
            
        # Check if this is a file we should keep
        if file_name in files_to_keep:
            kept_files.append(file_name)
            continue
            
        # Check if this is a temporary file (starts with ~$)
        if file_name.startswith('~$'):
            try:
                file_path.unlink()
                deleted_files.append(f"Temporary file: {file_name}")
            except Exception as e:
                print(f"Error deleting temporary file {file_name}: {e}")
            continue
            
        # Check if this is a JSON file (individual report)
        if file_name.endswith('.json') and file_name != 'reports.json':
            try:
                # Check if this report is already in reports.json
                report_id = file_path.stem
                reports_file = REPORTS_DIR / 'reports.json'
                
                if reports_file.exists():
                    with open(reports_file, 'r', encoding='utf-8') as f:
                        try:
                            reports_data = json.load(f)
                            # If report is not in reports.json, delete it
                            if report_id not in reports_data:
                                file_path.unlink()
                                deleted_files.append(f"Orphaned report: {file_name}")
                                continue
                        except json.JSONDecodeError:
                            print(f"Error reading {reports_file}, skipping cleanup of {file_name}")
                            
            except Exception as e:
                print(f"Error processing {file_name}: {e}")
    
    # Print summary
    print("\nCleanup complete!")
    print(f"Files kept: {len(kept_files)}")
    if kept_files:
        print("  - " + "\n  - ".join(kept_files))
    
    print(f"\nFiles deleted: {len(deleted_files)}")
    if deleted_files:
        print("  - " + "\n  - ".join(deleted_files))

if __name__ == "__main__":
    cleanup_reports()

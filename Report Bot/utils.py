import logging
from datetime import datetime

# Logger setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)



def get_current_date():
    """Get current date in a suitable format"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def escape_markdown(text, force=False):
    """Escape special MarkdownV2 characters
    
    Args:
        text: The text to escape (can be any type, will be converted to string)
        force: If True, force escaping even if text might already be escaped
    """
    if text is None:
        return ""
        
    # Convert to string if not already
    text_str = str(text)
    
    # If empty string after conversion
    if not text_str:
        return ""
    
    # If text is already escaped and we're not forcing, return as is
    if not force and '\\_' in text_str:
        return text_str
        
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return ''.join(['\\' + char if char in escape_chars else char for char in text_str])

def format_report(user_data, escape_text=True):
    """قالب‌بندی گزارش نهایی با پشتیبانی از چندین مشکل
    
    Args:
        user_data: Dictionary containing report data
        escape_text: Whether to escape markdown characters (set to False if text is already escaped)
    """
    def safe_escape(text):
        """Helper to safely escape text only if needed
        
        Args:
            text: The text to escape (can be any type)
            
        Returns:
            str: The escaped text, or empty string if text is None/empty
        """
        if text is None:
            return ""
            
        # Convert to string if not already
        text_str = str(text)
        
        if not escape_text or not text_str:
            return text_str
            
        return escape_markdown(text_str, force=False)
        
    employee_name = safe_escape(user_data.get('employee', 'Unknown'))
    
    # Handle multiple servers if available, otherwise fall back to single server
    servers = user_data.get('servers', [])
    if not servers and 'server' in user_data:
        servers = [user_data['server']]
        
    # Clean up any duplicate additional_info
    if 'additional_info' in user_data and user_data['additional_info'] in ['', None]:
        del user_data['additional_info']
    
    report = "📅 *Daily Report*\n\n"
    
    # Add employee information
    report += f"👤 *Employee:* {employee_name}\n"
    
    # Add additional employee information if available
    employee_data = user_data.get('employee_data', {})
    if employee_data:
        unit = escape_markdown(employee_data.get('unit', 'Unknown'))
        work_hours = escape_markdown(employee_data.get('work_hours', 'Unknown'))
        work_location = escape_markdown(employee_data.get('work_location', 'Unknown'))
        
        report += f"🏢 *Department:* {unit}\n"
        report += f"🕒 *Work Hours:* {work_hours}\n"
        report += f"📍 *Work Location:* {work_location}\n"
        
        special_conditions = [escape_markdown(cond) for cond in employee_data.get('special_conditions', [])]
        if special_conditions:
            report += f"📌 *Special Conditions:* {', '.join(special_conditions)}\n"
    
    # Add server information
    if servers:
        servers_text = ', '.join(escape_markdown(s) for s in servers)
        report += f"\n🖥️ *Servers:* {servers_text}\n"
    
    # Add work sections if available
    work_sections = user_data.get('work_sections', [])
    if work_sections:
        sections_text = ', '.join(escape_markdown(section) for section in work_sections)
        report += f"📋 *Work Sections:* {sections_text}\n"
    
    report += f"📅 *Date & Time:* {escape_markdown(get_current_date())}\n\n"
    
    # Handle multiple problems if available, otherwise fall back to single problem
    problems = user_data.get('problems', [])
    
    if problems:
        report += "⚠️ *Reported Issues:*\n\n"
        
        for i, problem in enumerate(problems, 1):
            # Get problem details with proper fallbacks
            problem_type = problem.get('type', 'Unknown')
            problem_category = problem.get('category', problem_type)  # Fallback to type if category not set
            problem_subtype = problem.get('subtype', '')
            problem_desc = problem.get('description', 'None')
            
            # Escape all text for markdown
            problem_type = escape_markdown(problem_type)
            problem_category = escape_markdown(problem_category)
            problem_subtype = escape_markdown(problem_subtype)
            problem_desc = escape_markdown(problem_desc)
            
            # Display problem number and type
            report += f"{i}\. *{problem_type}*\n"
            
            # Display category if it's different from type
            if problem_category and problem_category != problem_type:
                report += f"\- Category: {problem_category}\n"
            
            # Add subtype if it exists and is different from both type and category
            if problem_subtype and problem_subtype != problem_type and problem_subtype != problem_category:
                report += f"\- Subcategory: {problem_subtype}\n"
            
            # Handle live event details if this is a live event problem
            is_live_event = False
            
            # Check different possible indicators of a live event
            if (problem.get('type') in ['پخش', 'پخش زنده', 'Live Event'] or 
                problem.get('subtype') == 'پخش زنده' or
                problem.get('live_event_name') or 
                problem.get('live_event_source')):
                
                is_live_event = True
                
                # First try to get from the problem itself (new format)
                live_event_name = escape_markdown(problem.get('live_event_name', 'Unknown'))
                live_event_source = escape_markdown(problem.get('live_event_source', 'Unknown'))
                
                # Fall back to live_events dictionary (old format) if not found in problem
                if live_event_name == 'Unknown' or live_event_source == 'Unknown':
                    live_events = user_data.get('live_events', {})
                    live_event = live_events.get(str(i-1), {})  # problems are 0-based in user_data
                    
                    if live_event_name == 'Unknown':
                        live_event_name = escape_markdown(live_event.get('name', 'Unknown'))
                    if live_event_source == 'Unknown':
                        live_event_source = escape_markdown(live_event.get('source', 'Unknown'))
                
                report += f"\- Program: {live_event_name}\n"
                report += f"\- Source: {live_event_source}\n"
            
            # Add problem description if exists
            if problem_desc and problem_desc != 'None':
                report += f"\- Description: {problem_desc}\n"
            
            report += "\n"  # Add extra newline after each problem
    elif 'problem_type' in user_data:
        # Fallback for single problem format (for backward compatibility)
        problem_type = escape_markdown(user_data.get('problem_type', 'Unknown'))
        report += "⚠️ *Reported Problem:*\n"
        report += f"\- Problem Type: {problem_type}\n"
        
        if user_data['problem_type'] == 'Live Broadcast':
            live_event_name = escape_markdown(user_data.get('live_event_name', 'Unknown'))
            live_event_source = escape_markdown(user_data.get('live_event_source', 'Unknown'))
            report += f"\- Program: {live_event_name}\n"
            report += f"\- Problem Source: {live_event_source}\n"
        
        problem_desc = escape_markdown(user_data.get('problem_description', 'None'))
        report += f"\- Description: {problem_desc}\n\n"
    else:
        report += "✅ *No Problems Reported*\n\n"
    
    # Add rating and mood if available and not in manager feedback section
    if not any(('manager_rating' in user_data, 'manager_comment' in user_data)):
        if 'rating' in user_data or 'mood' in user_data:
            rating = escape_markdown(user_data.get('rating', 'Not rated'))
            mood = escape_markdown(user_data.get('mood', 'Not specified'))
            report += f"⭐ *Performance Rating:* {rating}/10\n"
            report += f"😊 *Mood:* {mood}\n\n"
    
    # Add additional info if available (only add once)
    if 'additional_info' in user_data and user_data['additional_info'] not in [None, '']:
        additional_info = safe_escape(user_data.get('additional_info', 'ندارد'))
        # Only add if not already in the report to prevent duplication
        if f"📝 *Additional Comments:*" not in report:
            report += f"\n📝 *Additional Comments:*\n{additional_info}\n"
    
    return report

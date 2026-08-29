import logging
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
import uuid
import sys
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from config import ADMIN_CHAT_ID
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, CallbackContext, ConversationHandler, CallbackQueryHandler
)
from telegram.helpers import escape_markdown

from config import (
    TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID,
    SERVERS, PROBLEM_TYPES, LIVE_EVENT_SOURCES, WORK_SECTIONS,
    PROBLEM_CATEGORIES, PROBLEM_SUBCATEGORIES
)
from utils import format_report, get_current_date
from excel_handler import save_to_excel

# String localization
def get_strings(lang: str = 'en') -> dict:
    """Get localized strings for the specified language
    
    Args:
        lang: Language code (default: 'en')
        
    Returns:
        dict: Dictionary of localized strings
    """
    # Default English strings
    strings = {
        'en': {
            'welcome': "👋 Welcome to the Daily Report Bot!",
            'select_name': "Please select your name from the list below:",
            'error_start': "⚠️ An error occurred while starting the bot. Please try again.",
            'operation_cancelled': "Operation cancelled. Use /start to begin again.",
            'help_text': (
                "🤖 *Daily Report Bot Help*\n\n"
                "Available commands:\\n"
                "/start - Start a new report\\n"
                "/help - Show this help message\\n"
                "/whoreported - Check who has reported today\\n"
                "/cancel - Cancel current operation\\n"
                "/skip - Skip current step\\n"
                "/finish - Complete and submit report\\n\\n"
                "This bot helps you easily submit your daily reports."
            ),
            'feedback_submitted': "✅ Feedback submitted successfully.",
            'error_saving_feedback': "❌ An error occurred while saving your feedback.",
            'critical_error': "⚠️ A critical error occurred. Please try again or contact support.",
            'error_occurred': "⚠️ An error occurred. Please try again.",
            'system_error': "⚠️ A system error occurred. Please try again.",
            'timeout_error': "⏱️ Operation timed out. Please try again.",
            'invalid_input': "⚠️ Invalid input. Please try again.",
            'preparing_report': "Preparing final report...",
            'error_sending_report': "❌ Error sending final report. Please try again.",
            'report_success': "📋 Report submitted successfully!",
            'select_work_sections': "Please select the work sections you were involved in:",
            'confirm_sections': "Confirm and Continue",
            'select_servers': "Please select the servers you worked with:",
            'any_problems': "Did you encounter any problems today?",
            'select_problem_type': "Please select the type of problem:",
            'problem_description': "Please describe the problem:",
            'rate_shift': "How would you rate your shift today?",
            'select_mood': "How are you feeling today?",
            'additional_comments': "Type Any comments or /skip",
            'report_complete': "✅ Thank you! Your report has been submitted.",
            'yes': "Yes",
            'no': "No",
            'skip': "Skip",
            'submit': "Submit",
            'back': "Back",
            'cancel': "Cancel",
            'retry': "Retry",
            'yes': "Yes",
            'no': "No",
            'done': "Done",
            'next': "Next",
            'previous': "Previous",
            'select_server': "Select Server"
        },
        # Add more languages here if needed
        'fa': {
            # Persian translations would go here
        }
    }
    
    # Return the requested language if available, otherwise default to English
    return strings.get(lang, strings['en'])

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/report_bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
logger.info("Starting Report Bot...")

# Load employee data from JSON file
def load_employees():
    try:
        # First try to load the English version
        json_path = Path(__file__).resolve().parent.parent / 'Analytics' / 'employees_en.json'
        if not json_path.exists():
            logger.warning(f"English employee file not found at {json_path}")
            # Fall back to original if English version doesn't exist
            json_path = Path(__file__).parent / 'employees.json'
            logger.info(f"Trying to load from {json_path}")
            
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            employees = data.get('employees', [])
            # Create a list of employee data with both display formats
            employee_list = []
            logger.info(f"Found {len(employees)} employees in the file")
            for emp in employees:
                name = emp.get('name', '')
                unit = emp.get('unit', '')
                work_hours = emp.get('work_hours', '')
                # Full display for other parts of the app (English only)
                full_display = f"{name} - {unit} ({work_hours})" if work_hours else f"{name} - {unit}"
                # Simple display (just name) for selection menu
                simple_display = name
                employee_list.append({
                    'display': simple_display,  # Just show name in the list
                    'simple_display': simple_display,
                    'data': emp
                })
            return employee_list
    except Exception as e:
        logger.error(f"Error loading employees: {e}", exc_info=True)
        return []

# Load employees data
EMPLOYEES = load_employees()

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define conversation states
SELECTING_EMPLOYEE = 0
SELECTING_WORK_SECTIONS = 1
SELECTING_SERVER = 2
ASK_PROBLEM = 3
PROBLEM_CATEGORY = 4
PROBLEM_TYPE = 5
LIVE_EVENT_NAME = 6
LIVE_EVENT_SOURCE = 7
PROBLEM_DESCRIPTION = 8
RATING = 9
MOOD = 10
ADDITIONAL_INFO = 11
DOCUMENT_UPLOAD = 12
ASK_MORE_PROBLEMS = 13
FINISH = 14
MANAGER_APPROVAL = 15
MANAGER_RATING = 16
MANAGER_COMMENT = 17

# Rating workflow states
RATING_MENU = 100
RATING_SCORE = 101
RATING_MOOD = 102
RATING_COMMENT = 103
RATING_CONFIRM = 104

# Manager ID for restricted access
MANAGER_ID = "858324589"

def manager_required(func):
    """Decorator to restrict access to manager only"""
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        user = update.effective_user
        if str(user.id) != MANAGER_ID:
            await update.message.reply_text(
                "🔒 *Access Denied*\n\n"
                "This command is restricted to the manager only.",
                parse_mode='Markdown'
            )
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# Define conversation states for Leader Report
LEADER_RATING, LEADER_STAFF, LEADER_ISSUE, LEADER_COMMENT = range(200, 204)

def create_vertical_keyboard(items: list, prefix: str, columns: int = 3) -> InlineKeyboardMarkup:
    """Create a keyboard with the given items arranged in the specified number of columns.
    
    Args:
        items: List of items to display as buttons
        prefix: Prefix for callback data (e.g., 'emp', 'srv')
        columns: Number of columns to arrange the buttons (2 or 3)
        
    Returns:
        InlineKeyboardMarkup: Configured keyboard markup with at least one button
    """
    # Ensure columns is between 2 and 3
    columns = max(2, min(3, columns))
    
    # Create rows of buttons with the specified number of columns
    keyboard = []
    
    # If no items, return a keyboard with a single 'No options available' button
    if not items:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("No options available", callback_data="none")]
        ])
    
    # Create the keyboard rows
    for i in range(0, len(items), columns):
        row = []
        for j in range(columns):
            if i + j < len(items):
                row.append(InlineKeyboardButton(
                    str(items[i + j]), 
                    callback_data=f"{prefix}_{i + j}"
                ))
        if row:  # Only add non-empty rows
            keyboard.append(row)
    
    # Ensure we have at least one button
    if not keyboard:
        keyboard = [[InlineKeyboardButton("Continue", callback_data=f"{prefix}_continue")]]
            
    return InlineKeyboardMarkup(keyboard)


# Mood emojis
MOODS = {
    'happy': '😊 Happy',
    'neutral': '😐 Normal',
    'sad': '😔 Sad'
}

# دستور شروع
async def start(update: Update, context: CallbackContext) -> int:
    """Start the bot and request employee selection
    
    Args:
        update: Update object containing the start command
        context: Callback context for the conversation
        
    Returns:
        int: Next conversation state (SELECTING_EMPLOYEE) or ConversationHandler.END on error
    """
    try:
        if not update.message:
            logger.error("No message in update")
            return ConversationHandler.END
            
        user = update.effective_user
        logger.info(f"User {user.id} started the bot")
        
        # Reset user data at start
        context.user_data.clear()
        
        # Clear any existing conversation state
        if '_conversation_state' in context.user_data:
            del context.user_data['_conversation_state']
            
        # Clear any existing report data
        for key in list(context.user_data.keys()):
            if key not in ['_conversation_state']:  # Keep conversation state if exists
                del context.user_data[key]
        
        # Set default language to English
        context.user_data['language'] = 'en'
        
        # Create employee selection keyboard with simple display names in 3 columns
        employee_names = [emp['simple_display'] for emp in EMPLOYEES]
        reply_markup = create_vertical_keyboard(employee_names, 'emp', columns=3)
        
        # Welcome message with better formatting
        welcome_text = (
            "✨ *Welcome to Daily Report Bot!* ✨\n\n"
            "Let's get started with your daily report.\n"
            "First, please select your name from the list below:"
        )
        
        # Remove the default command keyboard and show welcome message
        try:
            # Delete any existing start messages to keep chat clean
            if 'start_message_id' in context.user_data:
                try:
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=context.user_data['start_message_id']
                    )
                except Exception as e:
                    logger.warning(f"Could not delete previous start message: {e}")
            
            # Send welcome message
            welcome_msg = await update.message.reply_text(
                welcome_text,
                reply_markup=ReplyKeyboardRemove(),
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Store the welcome message ID for later cleanup
            context.user_data['start_message_id'] = welcome_msg.message_id
            
            # Add a small delay for better UX
            await asyncio.sleep(0.5)
            
            # Send the employee selection keyboard
            select_msg = await update.message.reply_text(
                "👤 *Select your name:*",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Store the selection message ID for cleanup
            context.user_data['select_message_id'] = select_msg.message_id
            
            return SELECTING_EMPLOYEE
            
        except Exception as e:
            logger.error(f"Error sending welcome message: {e}")
            raise
        
    except Exception as e:
        logger.error(f"Error in start command: {e}", exc_info=True)
        try:
            if update.message:
                await update.message.reply_text(
                    "❌ *Oops! Something went wrong.*\n"
                    "Please try again or contact support if the issue persists.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=ReplyKeyboardRemove()
                )
        except Exception as send_error:
            logger.error(f"Could not send error message: {send_error}")
        return ConversationHandler.END

async def employee_selected(update: Update, context: CallbackContext) -> int:
    """پس از انتخاب کارمند، سرور را سؤال می‌کند
    
    Args:
        update: Update object containing the callback query
        context: Callback context for the conversation
        
    Returns:
        int: Next conversation state or ConversationHandler.END on error
    """
    try:
        if not update.callback_query:
            logger.error("No callback_query in update")
            return ConversationHandler.END
            
        query = update.callback_query
        await query.answer()
        
        logger.info(f"[employee_selected] Received callback data: {query.data}")
        
        # Validate and process employee selection
        try:
            emp_idx = int(query.data.split('_')[1])
            if not (0 <= emp_idx < len(EMPLOYEES)):
                raise ValueError(f"Invalid employee index: {emp_idx}")
                
            selected_employee = EMPLOYEES[emp_idx]
            # Store both display name and full employee data
            context.user_data['employee'] = selected_employee['display']
            context.user_data['employee_data'] = selected_employee['data']
            logger.info(f"[employee_selected] Selected employee: {selected_employee['display']}")
            
        except (IndexError, ValueError) as e:
            logger.error(f"[employee_selected] Invalid employee selection: {e}", exc_info=True)
            await query.edit_message_text(
                "⚠️ انتخاب نامعتبر. لطفاً دوباره تلاش کنید.",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
            
        # Initialize selected_sections in user_data if it doesn't exist
        if 'selected_sections' not in context.user_data:
            context.user_data['selected_sections'] = []
            
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        # Create work sections selection keyboard with checkboxes
        keyboard = []
        for i, section in enumerate(WORK_SECTIONS):
            keyboard.append([
                InlineKeyboardButton(
                    f"☑️ {section}" if i in context.user_data['selected_sections'] else f"⬜ {section}",
                    callback_data=f"section_{i}"
                )
            ])
        
        # Add confirm button if at least one section is selected
        if context.user_data['selected_sections']:
            keyboard.append([
                InlineKeyboardButton(f"✅ {strings['confirm_sections']}", callback_data="sections_done")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Create a keyboard for error messages
        retry_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(strings['retry'], callback_data="retry")],
            [InlineKeyboardButton(strings['cancel'], callback_data="cancel")]
        ])
            
        # Send work sections selection prompt
        try:
            await query.edit_message_text(
                f"👤 Selected employee: {selected_employee['simple_display']}\n\n"
                f"{strings['select_work_sections']}",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info("[employee_selected] Successfully sent work sections selection prompt")
            return SELECTING_WORK_SECTIONS
            
        except Exception as edit_error:
            logger.error(f"[employee_selected] Error editing message: {edit_error}")
            # If editing fails, send a new message
            try:
                # First, try to send a new message with the keyboard
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"👤 Selected employee: {selected_employee['simple_display']}\n\n"
                        f"{strings['select_servers']}",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                return SELECTING_SERVER
            except Exception as send_error:
                logger.error(f"[employee_selected] Failed to send new message: {send_error}")
                # If sending new message fails, try to edit with a simple message and retry options
                try:
                    await query.edit_message_text(
                        f"⚠️ {strings['error_occurred']} {strings['retry']}",
                        reply_markup=retry_keyboard
                    )
                    return ConversationHandler.END
                except Exception as final_error:
                    logger.error(f"[employee_selected] Final error handling failed: {final_error}")
                    return ConversationHandler.END
        
    except Exception as e:
        logger.critical(f"[employee_selected] Unexpected error: {e}", exc_info=True)
        try:
            if 'query' in locals():
                await query.edit_message_text(
                    "⚠️ خطای غیرمنتظره‌ای رخ داد. لطفاً دوباره تلاش کنید.",
                    reply_markup=ReplyKeyboardRemove()
                )
            else:
                # If we can't edit the message, try to send a new one
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="⚠️ خطای غیرمنتظره‌ای رخ داد. لطفاً دوباره تلاش کنید.",
                    reply_markup=ReplyKeyboardRemove()
                )
        except Exception as send_error:
            logger.error(f"[employee_selected] Failed to send error message: {send_error}")
            
        return ConversationHandler.END

async def handle_work_sections(update: Update, context: CallbackContext) -> int:
    """پردازش انتخاب بخش‌های کاری
    
    Args:
        update: Update object containing the callback query
        context: Callback context for the conversation
        
    Returns:
        int: Next conversation state (SELECTING_SERVER or ASK_PROBLEM) or ConversationHandler.END on error
    """
    try:
        logger.info("[handle_work_sections] Function started")
        
        if not update.callback_query:
            logger.error("[handle_work_sections] No callback_query in update")
            return ConversationHandler.END
            
        query = update.callback_query
        if not query or not query.data:
            logger.error("[handle_work_sections] No query or query.data in update")
            return ConversationHandler.END
            
        await query.answer()
        
        # Get the callback data
        callback_data = query.data
        logger.info(f"[handle_work_sections] Received callback data: {callback_data}")
        logger.debug(f"[handle_work_sections] Current user_data: {json.dumps(context.user_data, default=str, ensure_ascii=False)}")
        
        # Initialize user data if not exists
        if 'selected_sections' not in context.user_data:
            context.user_data['selected_sections'] = []
            logger.debug("[handle_work_sections] Initialized selected_sections in user_data")
        
        # Handle section selection/deselection
        if 'section_' in callback_data:
            try:
                section_idx = int(callback_data.split('_')[1])
                logger.info(f"[handle_work_sections] Processing section selection: {section_idx}")
                
                # Validate section index
                if not (0 <= section_idx < len(WORK_SECTIONS)):
                    raise ValueError(f"Invalid section index: {section_idx}")
                
                # Toggle section selection
                if 'selected_sections' not in context.user_data:
                    context.user_data['selected_sections'] = []
                    
                if section_idx in context.user_data['selected_sections']:
                    context.user_data['selected_sections'].remove(section_idx)
                else:
                    context.user_data['selected_sections'].append(section_idx)
                
                # Get language strings
                lang = context.user_data.get('language', 'en')
                strings = get_strings(lang)
                
                # Create work sections keyboard with checkboxes
                keyboard = []
                
                # Add work section buttons
                for i, section in enumerate(WORK_SECTIONS):
                    if i < len(WORK_SECTIONS):  # Ensure index is valid
                        keyboard.append([
                            InlineKeyboardButton(
                                f"☑️ {section}" if i in context.user_data['selected_sections'] else f"⬜ {section}",
                                callback_data=f"section_{i}"
                            )
                        ])
                
                # Ensure we have at least one section button
                if not keyboard:
                    keyboard.append([
                        InlineKeyboardButton("No work sections available", callback_data="none")
                    ])
                # Add confirm button if any sections are selected
                elif context.user_data['selected_sections']:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"✅ {strings.get('confirm_sections', 'Confirm and Continue')}", 
                            callback_data="sections_done"
                        )
                    ])
                
                # Ensure we have a valid keyboard
                if not keyboard:
                    keyboard = [[
                        InlineKeyboardButton("Continue", callback_data="sections_done")
                    ]]
                    
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Update the message with the new keyboard
                try:
                    await query.edit_message_text(
                        f"👤 Selected employee: {context.user_data.get('employee', '')}\n\n"
                        f"{strings.get('select_work_sections', 'Please select the work sections you were involved in:')}",
                        reply_markup=reply_markup
                    )
                except Exception as edit_error:
                    logger.error(f"[handle_work_sections] Error editing message: {edit_error}")
                    # If editing fails, send a new message
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=f"👤 Selected employee: {context.user_data.get('employee', '')}\n\n"
                             f"{strings.get('select_work_sections', 'Please select the work sections you were involved in:')}",
                        reply_markup=reply_markup
                    )
                    # Try to delete the old message
                    try:
                        await query.message.delete()
                    except:
                        pass
                
                return SELECTING_WORK_SECTIONS
                
            except (IndexError, ValueError) as e:
                logger.error(f"[handle_work_sections] Error processing section selection: {e}")
                await query.edit_message_text(
                    "⚠️ Error processing section selection. Please try again.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return ConversationHandler.END
                
        # Handle confirmation
        elif query.data == "sections_done":
            logger.info("[handle_work_sections] Processing sections_done callback")
            
            # Get language strings
            lang = context.user_data.get('language', 'en')
            strings = get_strings(lang)
            
            # Ensure we have selected sections
            if not context.user_data.get('selected_sections'):
                logger.warning("[handle_work_sections] No sections selected when confirming")
                await query.answer("Please select at least one section.", show_alert=True)
                return SELECTING_WORK_SECTIONS
                
            # Log current state before transition
            logger.info(f"[handle_work_sections] Current state before transition: {context.user_data.get('_conversation_state')}")
            
            # Store selected sections in user_data
            selected_sections = [WORK_SECTIONS[i] for i in sorted(context.user_data['selected_sections'])]
            context.user_data['work_sections'] = selected_sections
            
            # Log the selected sections for debugging
            logger.info(f"[handle_work_sections] Selected sections: {selected_sections}")
            
            # Check if Broadcast section is selected (server selection is only for Broadcast)
            broadcast_sections = ["broadcast", "پخش"]
            has_server_requirement = any(
                any(broadcast_section in section.lower() for broadcast_section in broadcast_sections)
                for section in selected_sections
            )
            
            logger.info(f"[handle_work_sections] Server required: {has_server_requirement}")
            
            # Set the next state based on whether server selection is required
            if has_server_requirement:
                # Force update the conversation state for server selection
                context.user_data['_conversation_state'] = SELECTING_SERVER
                logger.info("[handle_work_sections] Transitioning to SELECTING_SERVER state")
            else:
                # Skip directly to problem question
                context.user_data['_conversation_state'] = ASK_PROBLEM
                logger.info("[handle_work_sections] Transitioning to ASK_PROBLEM state")
                
                # Prepare the message for the problem question
                message_text = f"✅ Selected sections: {', '.join(selected_sections)}\n\n"
                message_text += "❓ Did you encounter any problems today?"
                
                # Create the keyboard for the problem question
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Yes", callback_data="problem_yes"),
                        InlineKeyboardButton("❌ No", callback_data="problem_no")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Edit the message with the problem question
                await query.edit_message_text(
                    text=message_text,
                    reply_markup=reply_markup
                )
                return ASK_PROBLEM
            
            if has_server_requirement:
                # Initialize selected_servers list if not exists
                if 'selected_servers' not in context.user_data:
                    context.user_data['selected_servers'] = []
                
                # Create multi-select keyboard for servers
                keyboard = []
                for i, server in enumerate(SERVERS):
                    keyboard.append([
                        InlineKeyboardButton(
                            f"☑️ {server}" if i in context.user_data['selected_servers'] else f"⬜ {server}",
                            callback_data=f"srv_{i}"
                        )
                    ])
                
                # Add confirm button if at least one server is selected
                if context.user_data['selected_servers']:
                    keyboard.append([
                        InlineKeyboardButton(f"✅ {strings['confirm_sections']}", callback_data="servers_done")
                    ])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                try:
                    await query.edit_message_text(
                        f"✅ Selected sections: {', '.join(selected_sections)}\n\n"
                        f"🖥️ Please select the server(s) you worked with (you can select multiple):",
                        reply_markup=reply_markup
                    )
                    return SELECTING_SERVER
                except Exception as e:
                    logger.error(f"[handle_work_sections] Error showing server selection: {e}")
                    await query.edit_message_text(
                        "⚠️ Error showing server selection. Please try again.",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    return ConversationHandler.END
            else:
                # Skip server selection if no server-requiring sections are selected
                try:
                    # First, try to answer any pending callback
                    try:
                        await query.answer()
                    except Exception as e:
                        logger.warning(f"[handle_work_sections] Error answering callback: {e}")
                    
                    # Then edit the message
                    await query.edit_message_text(
                        f"✅ Selected sections: {', '.join(selected_sections)}\n\n"
                        f"{strings['any_problems']}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(f"✅ {strings['problem_yes']}", callback_data="problem_yes")],
                            [InlineKeyboardButton(f"❌ {strings['problem_no']}", callback_data="problem_no")]
                        ])
                    )
                    logger.info("[handle_work_sections] Transitioning to ASK_PROBLEM state")
                    return ASK_PROBLEM
                except Exception as e:
                    logger.error(f"[handle_work_sections] Error showing problem question: {e}")
                    await query.edit_message_text(
                        "⚠️ Error showing question. Please try again.",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    return ConversationHandler.END
        
        else:
            logger.warning(f"[handle_work_sections] Unknown callback data: {query.data}")
            return SELECTING_WORK_SECTIONS
            
    except Exception as e:
        logger.error(f"[handle_work_sections] Unexpected error: {e}", exc_info=True)
        try:
            if 'query' in locals():
                await query.edit_message_text(
                    "⚠️ An error occurred while processing your request. Please try again.",
                    reply_markup=retry_keyboard
                )
        except:
            pass
        return ConversationHandler.END

async def server_selected(update: Update, context: CallbackContext) -> int:
    """پس از انتخاب سرورها، سوال مشکل را می‌پرسد
    
    Args:
        update: Update object containing the callback query
        context: Callback context for the conversation
        
    Returns:
        int: Next conversation state (ASK_PROBLEM) or current state if still selecting
    """
    try:
        logger.info("[server_selected] Function started")
        
        # Get language strings at the start of the function
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        if not update.callback_query:
            logger.error("[server_selected] No callback_query in update")
            return ConversationHandler.END
            
        query = update.callback_query
        await query.answer()
        
        logger.info(f"[server_selected] Received callback data: {query.data}")
        logger.info(f"[server_selected] Current state: {context.user_data.get('_conversation_state')}")
        logger.info(f"[server_selected] User data: {json.dumps(context.user_data, default=str, ensure_ascii=False, indent=2)}")
        
        # Log the entire update object for debugging
        logger.debug(f"[server_selected] Update object: {update.to_dict()}")
        
        # Initialize selected_servers list if not exists
        if 'selected_servers' not in context.user_data:
            context.user_data['selected_servers'] = []
        
        def create_servers_keyboard():
            """Helper function to create the servers selection keyboard"""
            keyboard = []
            for i, server in enumerate(SERVERS):
                keyboard.append([
                    InlineKeyboardButton(
                        f"☑️ {server}" if i in context.user_data['selected_servers'] else f"⬜ {server}",
                        callback_data=f"srv_{i}"
                    )
                ])
            
            # Add confirm button if at least one server is selected
            if context.user_data['selected_servers']:
                keyboard.append([
                    InlineKeyboardButton(f"✅ {strings['confirm_sections']}", callback_data="servers_done")
                ])
            
            return InlineKeyboardMarkup(keyboard)
        
        # Handle server selection/deselection
        if query.data.startswith('srv_'):
            try:
                server_idx = int(query.data.split('_')[1])
                if not (0 <= server_idx < len(SERVERS)):
                    raise ValueError(f"Invalid server index: {server_idx}")
                
                # Toggle server selection
                if server_idx in context.user_data['selected_servers']:
                    context.user_data['selected_servers'].remove(server_idx)
                else:
                    context.user_data['selected_servers'].append(server_idx)
                
                # Create the updated keyboard
                reply_markup = create_servers_keyboard()
                
                # Ensure we have a valid keyboard
                if not isinstance(reply_markup, InlineKeyboardMarkup):
                    logger.error("Invalid reply_markup, recreating keyboard")
                    reply_markup = create_servers_keyboard()
                
                try:
                    # Update the message with the new keyboard
                    await query.edit_message_text(
                        f"🖥️ {strings.get('select_server', 'Select Server')}\n"
                        f"After selecting all relevant servers, click the '{strings.get('confirm_sections', 'Confirm and Continue')}' button.",
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    logger.error(f"[server_selected] Error updating message: {e}")
                    # If editing fails, try to send a new message
                    try:
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text=f"🖥️ {strings.get('select_server', 'Select Server')}",
                            reply_markup=reply_markup
                        )
                        # Delete the old message to avoid confusion
                        try:
                            await query.message.delete()
                        except:
                            pass
                    except Exception as send_error:
                        logger.error(f"[server_selected] Failed to send new message: {send_error}")
                        raise
                return SELECTING_SERVER
                
            except (IndexError, ValueError) as e:
                logger.error(f"[server_selected] Error processing server selection: {e}")
                await query.edit_message_text(
                    "⚠️ Error processing server selection. Please try again.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return ConversationHandler.END
        
        # Handle confirmation
        elif query.data == "servers_done":
            logger.info("[server_selected] Processing servers_done callback")
            
            # Get language strings
            lang = context.user_data.get('language', 'en')
            strings = get_strings(lang)
            
            # Ensure we have selected servers
            if not context.user_data.get('selected_servers'):
                logger.warning("[server_selected] No servers selected when confirming")
                await query.answer("Please select at least one server.", show_alert=True)
                return SELECTING_SERVER
                
            # Log current state before transition
            logger.info(f"[server_selected] Current state before transition: {context.user_data.get('_conversation_state')}")
            
            # Force update the conversation state
            context.user_data['_conversation_state'] = ASK_PROBLEM
            logger.info(f"[server_selected] Forced state to ASK_PROBLEM: {ASK_PROBLEM}")
                
            # Store selected servers in user_data
            selected_servers = [SERVERS[i] for i in sorted(context.user_data['selected_servers'])]
            context.user_data['servers'] = selected_servers
            
            # Log the selected servers for debugging
            logger.info(f"[server_selected] Selected servers: {selected_servers}")
            
            # Prepare message with selected servers and work sections
            selected_sections = context.user_data.get('work_sections', [])
            sections_text = f"\n✅ Selected sections: {', '.join(selected_sections)}" if selected_sections else ""
            servers_text = f"🖥️ Selected servers: {', '.join(selected_servers)}"
            
            # Log the prepared message for debugging
            logger.info(f"[server_selected] Prepared message - Servers: {selected_servers}, Sections: {selected_sections}")
            
            # Ask if user faced any issues
            keyboard = [
                [
                    InlineKeyboardButton(f"✅ {strings['yes']}", callback_data="problem_yes"),
                    InlineKeyboardButton(f"❌ {strings['no']}", callback_data="problem_no")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Ensure we have the problem question string
            if 'problem_question' not in strings:
                strings['problem_question'] = "Did you encounter any problems today?"
            
            # Log the next state transition
            logger.info("[server_selected] Transitioning to ASK_PROBLEM state")
            
            try:
                # First, try to answer any pending callback
                try:
                    await query.answer()
                except Exception as e:
                    logger.warning(f"[server_selected] Error answering callback: {e}")
                
                # Then edit the message
                # Ensure we have a valid reply_markup
                if not isinstance(reply_markup, InlineKeyboardMarkup):
                    logger.error("Invalid reply_markup, creating a new one")
                    keyboard = [
                        [
                            InlineKeyboardButton(f"✅ {strings['yes']}", callback_data="problem_yes"),
                            InlineKeyboardButton(f"❌ {strings['no']}", callback_data="problem_no")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"{servers_text}{sections_text}\n\n"
                    f"{strings.get('problem_question', 'Did you encounter any problems today?')}",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.info("[server_selected] Successfully sent problem question")
                
                # Explicitly return the next state
                next_state = ASK_PROBLEM
                logger.info(f"[server_selected] Returning next state: {next_state}")
                return next_state
                
            except Exception as edit_error:
                logger.error(f"[server_selected] Error editing message: {edit_error}")
                # If editing fails, send a new message
                try:
                    # Ensure we have a valid reply_markup
                    if not isinstance(reply_markup, InlineKeyboardMarkup):
                        logger.error("Invalid reply_markup in fallback, creating a new one")
                        keyboard = [
                            [
                                InlineKeyboardButton(f"✅ {strings['yes']}", callback_data="problem_yes"),
                                InlineKeyboardButton(f"❌ {strings['no']}", callback_data="problem_no")
                            ]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=f"{servers_text}{sections_text}\n\n"
                             f"{strings.get('problem_question', 'Did you encounter any problems today?')}",
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return ASK_PROBLEM
                except Exception as send_error:
                    logger.error(f"[server_selected] Failed to send new message: {send_error}")
                    try:
                        await query.edit_message_text(
                            f"⚠️ {strings.get('error_occurred', 'An error occurred. Please try again.')}",
                            reply_markup=ReplyKeyboardRemove()
                        )
                    except:
                        pass
                    return ConversationHandler.END
        
        else:
            logger.warning(f"[server_selected] Unknown callback data: {query.data}")
            return SELECTING_SERVER
            
    except Exception as e:
        logger.critical(f"[server_selected] Unexpected error: {e}", exc_info=True)
        try:
            if 'query' in locals():
                await query.edit_message_text(
                    "⚠️ خطای غیرمنتظره‌ای رخ داد. لطفاً دوباره تلاش کنید.",
                    reply_markup=ReplyKeyboardRemove()
                )
            else:
                # If we can't edit the message, try to send a new one
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="⚠️ خطای غیرمنتظره‌ای رخ داد. لطفاً دوباره تلاش کنید.",
                    reply_markup=ReplyKeyboardRemove()
                )
        except Exception as send_error:
            logger.error(f"[server_selected] Failed to send error message: {send_error}")
            
        return ConversationHandler.END

async def handle_problem_type(update: Update, context: CallbackContext) -> int:
    """Handle problem type selection
    
    Args:
        update: Update object containing the callback query
        context: Callback context for the conversation
        
    Returns:
        int: Next conversation state or current state if still selecting
    """
    try:
        if not update.callback_query:
            logger.error("[handle_problem_type] No callback_query in update")
            return ConversationHandler.END
            
        query = update.callback_query
        await query.answer()
        
        logger.info(f"[handle_problem_type] Received callback data: {query.data}")
        
        # Initialize selected_problems list if not exists
        if 'selected_problems' not in context.user_data:
            context.user_data['selected_problems'] = []
        
        # Handle problem selection/deselection
        if query.data == 'problems_done':
            # User confirmed their problem selections
            if not context.user_data.get('selected_problems'):
                await query.answer("لطفاً حداقل یک مشکل را انتخاب کنید.", show_alert=True)
                return PROBLEM_TYPE
                
            # Store selected problem types
            selected_problems = [PROBLEM_TYPES[i] for i in sorted(context.user_data['selected_problems'])]
            context.user_data['problem_types'] = selected_problems
            
            # Ask for problem description
            await query.edit_message_text(
                "لطفاً توضیحی در مورد مشکل(های) به وجود آمده ارائه دهید:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("رد کردن", callback_data="skip_description")]
                ])
            )
            return PROBLEM_DESCRIPTION
            
        elif query.data == 'skip_description':
            # Skip problem description
            context.user_data['problem_description'] = "بدون توضیح"
            
            # Go to rating
            keyboard = [
                [InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(1, 6)],
                [InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(6, 11)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "به عملکرد امروز خود از 1 تا 10 چه امتیازی می‌دهید؟",
                reply_markup=reply_markup
            )
            return RATING
            
        # Handle problem selection/deselection
        if query.data.startswith('prob_'):
            try:
                prob_idx = int(query.data.split('_')[1])
                
                # Toggle problem selection
                if prob_idx in context.user_data['selected_problems']:
                    context.user_data['selected_problems'].remove(prob_idx)
                else:
                    context.user_data['selected_problems'].append(prob_idx)
                
                # Get language strings
                lang = context.user_data.get('language', 'en')
                strings = get_strings(lang)
                
                # Create problem type selection keyboard
                keyboard = []
                for i, problem_type in enumerate(PROBLEM_TYPES):
                    keyboard.append([
                        InlineKeyboardButton(
                            f"☑️ {problem_type}" if i in context.user_data['selected_problems'] else f"⬜ {problem_type}",
                            callback_data=f"prob_{i}"
                        )
                    ])
                
                # Add confirm button if at least one problem is selected
                if context.user_data['selected_problems']:
                    keyboard.append([
                        InlineKeyboardButton(f"✅ {strings['confirm_sections']}", callback_data="problems_done")
                    ])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Prepare context string with selected sections and servers
                sections_text = ""
                servers_text = ""
                if 'selected_sections' in context.user_data:
                    sections_text = f"\n✅ Selected sections: {', '.join(context.user_data['selected_sections'])}"
                if 'selected_servers' in context.user_data:
                    servers_text = f"🖥️ Selected servers: {', '.join(context.user_data['selected_servers'])}"
                
                context_str = ""
                if sections_text or servers_text:
                    context_str = f"{sections_text}{servers_text}\n\n"
                
                # Send message with problem type selection
                await query.edit_message_text(
                    f"{context_str}⚠️ Please select the type(s) of problem you encountered (you can select multiple):",
                    reply_markup=reply_markup
                )
                return PROBLEM_TYPE
                
            except (IndexError, ValueError) as e:
                logger.error(f"[handle_problem_type] Error processing problem selection: {e}")
                await query.edit_message_text(
                    "⚠️ Error processing problem selection. Please try again.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return ConversationHandler.END
        
        return PROBLEM_TYPE
        
    except Exception as e:
        logger.error(f"[handle_problem_type] Unexpected error: {e}", exc_info=True)
        try:
            if 'query' in locals():
                await query.edit_message_text(
                    "⚠️ An unexpected error occurred. Please try again.",
                    reply_markup=ReplyKeyboardRemove()
                )
        except:
            pass
        return ConversationHandler.END

async def handle_problem_description(update: Update, context: CallbackContext) -> int:
    """Handle problem description input
    
    Args:
        update: Update object containing the message
        context: Callback context for the conversation
        
    Returns:
        int: Next conversation state (RATING, LIVE_EVENT_SOURCE, or PROBLEM_DESCRIPTION) or current state on error
    """
    try:
        if not update.message or not update.message.text:
            raise ValueError("No message text provided")
        
        # Get current problem index and problems list
        current_idx = context.user_data.get('current_problem_idx', 0)
        problems = context.user_data.get('problems', [])
        
        if not problems or current_idx >= len(problems):
            logger.error(f"[handle_problem_description] Invalid problem index: {current_idx}, problems: {problems}")
            return await ask_for_rating(update, context)
        
        current_problem = problems[current_idx]
        
        # Check if we're waiting for live event name
        if context.user_data.get('awaiting_live_event_name', False):
            # Clear the flag first to prevent race conditions
            context.user_data['awaiting_live_event_name'] = False
            
            # Store the live event name
            live_event_name = update.message.text.strip()
            if not live_event_name:
                await update.message.reply_text(
                    "⚠️ نام برنامه زنده نمی‌تواند خالی باشد. لطفاً دوباره وارد کنید:"
                )
                context.user_data['awaiting_live_event_name'] = True
                return PROBLEM_DESCRIPTION
                
            try:
                # Store in live_events dictionary
                if 'live_events' not in context.user_data:
                    context.user_data['live_events'] = {}
                context.user_data['live_events'][str(current_idx)] = {'name': live_event_name}
                
                # Create keyboard for live event sources
                keyboard = [
                    [InlineKeyboardButton(src, callback_data=f"src_{i}")] 
                    for i, src in enumerate(LIVE_EVENT_SOURCES)
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Get context text
                selected_sections = context.user_data.get('work_sections', [])
                selected_servers = context.user_data.get('servers', [])
                
                context_text = []
                if selected_sections:
                    context_text.append(f"✅ بخش‌های انتخابی: {', '.join(selected_sections)}")
                if selected_servers:
                    context_text.append(f"🖥️ سرورهای انتخابی: {', '.join(selected_servers)}")
                context_str = '\n'.join(context_text) + '\n\n' if context_text else ''
                
                # Store that we're waiting for live event source
                context.user_data['awaiting_live_event_source'] = True
                
                # Send the message with the source selection keyboard
                message = await update.message.reply_text(
                    f"{context_str}"
                    f"📺 برنامه زنده: {live_event_name}\n\n"
                    f"🔍 لطفاً منبع مشکل را انتخاب کنید ({current_idx + 1}/{len(problems)}):",
                    reply_markup=reply_markup
                )
                
                # Store the message ID for later reference
                context.user_data['last_source_message_id'] = message.message_id
                
                # Explicitly return the next state
                return LIVE_EVENT_SOURCE
                
            except Exception as e:
                logger.error(f"Error handling live event name: {e}", exc_info=True)
                await update.message.reply_text(
                    "⚠️ خطایی در پردازش نام برنامه زنده رخ داد. لطفاً دوباره تلاش کنید."
                )
                context.user_data['awaiting_live_event_name'] = True
                return PROBLEM_DESCRIPTION
        
        # Handle regular problem description
        current_problem['description'] = update.message.text
        
        # Move to next problem that needs description
        next_problem_idx = next((i for i, p in enumerate(problems) 
                              if not p.get('description', '')), None)
        
        if next_problem_idx is not None:
            # Ask for description of next problem
            context.user_data['current_problem_idx'] = next_problem_idx
            next_problem = problems[next_problem_idx]
            
            # Get context text
            selected_sections = context.user_data.get('work_sections', [])
            selected_servers = context.user_data.get('servers', [])
            
            context_text = []
            if selected_sections:
                context_text.append(f"✅ بخش‌های انتخابی: {', '.join(selected_sections)}")
            if selected_servers:
                context_text.append(f"🖥️ سرورهای انتخابی: {', '.join(selected_servers)}")
            context_str = '\n'.join(context_text) + '\n\n' if context_text else ''
            
            if next_problem['type'] == "Live events":
                context.user_data['awaiting_live_event_name'] = True
                prompt_text = (
                    f"{context_str}"
                    f"🔴 مشکل در رویداد زنده ({next_problem_idx + 1}/{len(problems)})\n\n"
                    "📝 لطفاً نام برنامه زنده‌ای که مشکل داشته را وارد کنید:"
                )
            else:
                context.user_data['awaiting_live_event_name'] = False
                prompt_text = (
                    f"{context_str}"
                    f"🔧 مشکل در {next_problem['type']} ({next_problem_idx + 1}/{len(problems)})\n\n"
                    "📝 لطفاً مشکل را به طور دقیق توضیح دهید و راه‌حل‌های پیشنهادی خود را ذکر کنید:"
                )
            
            await update.message.reply_text(prompt_text)
            return PROBLEM_DESCRIPTION
        
        # No more problems, ask for rating
        return await ask_for_rating(update, context)
        
    except Exception as e:
        logger.error(f"[handle_problem_description] Error: {e}", exc_info=True)
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        await update.message.reply_text(
            "⚠️ Error processing description. Please try again.",
            reply_markup=ReplyKeyboardRemove()
        )
        return PROBLEM_DESCRIPTION

async def handle_live_event_source(update: Update, context: CallbackContext) -> int:
    """Handle live event source selection
    
    Args:
        update: Update object containing the callback query
        context: Callback context for the conversation
        
    Returns:
        int: Next conversation state (PROBLEM_DESCRIPTION or RATING)
    """
    try:
        if not update.callback_query:
            logger.error("[handle_live_event_source] No callback_query in update")
            return ConversationHandler.END
            
        query = update.callback_query
        await query.answer()
        
        # Get the selected source index
        try:
            src_idx = int(query.data.split('_')[1])
            if src_idx < 0 or src_idx >= len(LIVE_EVENT_SOURCES):
                raise ValueError("Invalid source index")
                
            # Get current problem
            current_idx = context.user_data.get('current_problem_idx', 0)
            problems = context.user_data.get('problems', [])
            
            if not problems or current_idx >= len(problems):
                logger.error("[handle_live_event_source] No current problem found")
                return await ask_for_rating(update, context)
                
            # Store the source
            problems[current_idx]['source'] = LIVE_EVENT_SOURCES[src_idx]
            
            # Ask for problem description
            await query.edit_message_text(
                f"📝 لطفاً مشکل به وجود آمده در رویداد زنده '{problems[current_idx].get('event_name', '')}' "
                f"از منبع {LIVE_EVENT_SOURCES[src_idx]} را به طور دقیق توضیح دهید:",
                reply_markup=ReplyKeyboardRemove()
            )
            
            # Mark that we're no longer waiting for live event name
            context.user_data['awaiting_live_event_name'] = False
            
            return PROBLEM_DESCRIPTION
            
        except (IndexError, ValueError) as e:
            logger.error(f"[handle_live_event_source] Error processing source selection: {e}")
            await query.edit_message_text(
                "⚠️ خطا در پردازش منبع رویداد. لطفاً دوباره تلاش کنید.",
                reply_markup=ReplyKeyboardRemove()
            )
            return PROBLEM_TYPE
            
    except Exception as e:
        logger.error(f"[handle_live_event_source] Unexpected error: {e}", exc_info=True)
        try:
            if 'query' in locals():
                await query.edit_message_text(
                    "⚠️ خطای غیرمنتظره‌ای رخ داد. لطفاً دوباره تلاش کنید.",
                    reply_markup=ReplyKeyboardRemove()
                )
        except:
            pass
        return PROBLEM_TYPE

async def handle_problem_response(update: Update, context: CallbackContext) -> int:
    """Process the response to the problem question
    
    Args:
        update: Update object containing the callback query
        context: Callback context for the conversation
        
    Returns:
        int: Next conversation state (PROBLEM_TYPE or RATING) or ConversationHandler.END on error
    """
    query = update.callback_query
    await query.answer()
    
    try:
        if not query.data:
            raise ValueError("No callback data provided")
        
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
            
        # Create a keyboard for error messages
        retry_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Try Again", callback_data="retry")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ])
            
        if query.data == "problem_yes":
            # Initialize problems list and current problem index if not exists
            if 'problems' not in context.user_data:
                context.user_data['problems'] = []
                
            # Initialize current problem index if not exists
            if 'current_problem_idx' not in context.user_data:
                context.user_data['current_problem_idx'] = 0
                
            # Initialize selected_problems list if not exists
            if 'selected_problems' not in context.user_data:
                context.user_data['selected_problems'] = []
            
            # Get selected sections for display
            selected_sections = context.user_data.get('work_sections', [])
            sections_text = f"\n✅ Selected sections: {', '.join(selected_sections)}" if selected_sections else ""
            
            # Get selected servers if exist
            selected_servers = context.user_data.get('servers', [])
            servers_text = f"\n🖥️ Selected servers: {', '.join(selected_servers)}" if selected_servers else ""
            
            # Check if problem types are configured
            if not PROBLEM_TYPES:
                logger.error("No problem types configured")
                raise ValueError("Problem types not configured")
            
            # Create keyboard for problem categories
            keyboard = []
            for i, category in enumerate(PROBLEM_CATEGORIES):
                keyboard.append([
                    InlineKeyboardButton(
                        category,
                        callback_data=f"cat_{i}"
                    )
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Prepare the message text
            message_text = f"{sections_text}{servers_text}\n\n"
            message_text += "⚠️ Please select the type(s) of problem you encountered (you can select multiple):\n"
            # Removed instruction text
            
            try:
                await query.edit_message_text(
                    message_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                return PROBLEM_TYPE
            except Exception as edit_error:
                logger.error(f"[handle_problem_response] Error editing message: {edit_error}")
                try:
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=message_text,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return PROBLEM_CATEGORY
                except Exception as send_error:
                    logger.error(f"[handle_problem_response] Failed to send new message: {send_error}")
                    try:
                        await query.edit_message_text(
                            "⚠️ An error occurred while displaying problem types. Please try again.",
                            reply_markup=retry_keyboard
                        )
                    except:
                        pass
                    return ConversationHandler.END
            
        elif query.data == "problem_no":
            # If user has no problems, go directly to rating question
            keyboard = [
                [InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(1, 6)],
                [InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(6, 11)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            rating_question = "How would you rate your performance today on a scale from 1 to 10?"
            
            try:
                await query.edit_message_text(
                    rating_question,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                return RATING
            except Exception as edit_error:
                logger.error(f"[handle_problem_response] Error editing message for rating: {edit_error}")
                try:
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=rating_question,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return RATING
                except Exception as send_error:
                    logger.error(f"[handle_problem_response] Failed to send rating question: {send_error}")
                    try:
                        await query.edit_message_text(
                            "⚠️ An error occurred while displaying the rating question. Please try again.",
                            reply_markup=retry_keyboard
                        )
                    except:
                        pass
                    return ConversationHandler.END
            
        else:
            raise ValueError(f"Unknown callback data: {query.data}")
            
    except Exception as e:
        logger.error(f"Error processing problem response: {e}", exc_info=True)
        
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        # Try to send error message, but don't fail if message editing fails
        try:
            await query.edit_message_text(
                "⚠️ An error occurred while processing your response. Please try again.",
                reply_markup=retry_keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as edit_error:
            logger.error(f"Failed to edit message: {edit_error}")
            try:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="An error occurred while processing your response. Please try again.",
                    reply_markup=retry_keyboard
                )
            except Exception as send_error:
                logger.error(f"Failed to send error message: {send_error}")
                
        return ConversationHandler.END

async def handle_rating(update: Update, context: CallbackContext) -> int:
    """Process performance rating"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        rating = int(query.data.split('_')[1])
        context.user_data['rating'] = rating
        
        # Create mood selection keyboard
        keyboard = [
            [
                InlineKeyboardButton("😊 Happy", callback_data="mood_happy"),
                InlineKeyboardButton("😐 Neutral", callback_data="mood_neutral"),
                InlineKeyboardButton("😔 Sad", callback_data="mood_sad")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"⭐ Your rating: {rating}/10\n\n"
            "How was your mood today?",
            reply_markup=reply_markup
        )
        return MOOD
        
    except (IndexError, ValueError) as e:
        logger.error(f"Error processing rating: {e}")
        await query.edit_message_text(
            "⚠️ An error occurred while processing your rating. Please try again.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

async def handle_mood(update: Update, context: CallbackContext) -> int:
    """Process mood selection"""
    try:
        if not update.callback_query:
            logger.error("[handle_mood] No callback_query in update")
            return ConversationHandler.END
            
        query = update.callback_query
        await query.answer()
        
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        try:
            mood_key = query.data.split('_')[1]  # e.g., 'happy' from 'mood_happy'
            mood_text = MOODS.get(mood_key, mood_key)
            context.user_data['mood'] = mood_text
            
            # Prepare the message text
            message_text = f"😊 Your mood: {mood_text}\n\n"
            message_text += "Enter any comments or /skip to continue."
            
            try:
                await query.edit_message_text(
                    message_text,
                    reply_markup=None  # Remove inline keyboard
                )
                return ADDITIONAL_INFO
                
            except Exception as edit_error:
                logger.error(f"[handle_mood] Error editing message: {edit_error}")
                # Fallback: Send new message if edit fails
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=message_text,
                    reply_markup=ReplyKeyboardRemove()
                )
                return ADDITIONAL_INFO
                
        except (IndexError, ValueError) as e:
            logger.error(f"[handle_mood] Error processing mood: {e}")
            await query.edit_message_text(
                "⚠️ An error occurred while processing your mood. Please try again.",
                reply_markup=None
            )
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"[handle_mood] Unexpected error: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                "⚠️ An unexpected error occurred. Please try again.",
                reply_markup=None
            )
        except:
            pass
        return ConversationHandler.END

async def handle_additional_info(update: Update, context: CallbackContext) -> int:
    """Process additional comments"""
    try:
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        additional_info = update.message.text
        context.user_data['additional_info'] = additional_info
        
        await update.message.reply_text(
            "✅ Your comments have been successfully saved.\n\n"
            "Finalizing your report..."
        )
        return await finish_report(update, context)
        
    except Exception as e:
        logger.error(f"Error processing additional comments: {e}")
        await update.message.reply_text(
            "⚠️ An error occurred while saving your comments. Please try again."
        )
        return ADDITIONAL_INFO

async def skip_additional_info(update: Update, context: CallbackContext) -> int:
    """Skip additional comments"""
    try:
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        context.user_data['additional_info'] = 'No additional comments'
        
        await update.message.reply_text(
            "✅ Skipped additional comments.\n\n"
            "Finalizing your report..."
        )
        return await finish_report(update, context)
        
    except Exception as e:
        logger.error(f"Error skipping additional comments: {e}")
        await update.message.reply_text(
            "⚠️ An error occurred while processing your request. Please try again."
        )
        return ADDITIONAL_INFO

async def handle_problem_category(update: Update, context: CallbackContext) -> int:
    """Handle problem category selection
    
    Args:
        update: Update object containing the callback query
        context: Callback context for the conversation
        
    Returns:
        int: Next conversation state (PROBLEM_TYPE for subcategories, or PROBLEM_DESCRIPTION)
    """
    try:
        if not update.callback_query:
            logger.error("[handle_problem_category] No callback_query in update")
            return ConversationHandler.END
            
        query = update.callback_query
        await query.answer()
        
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        logger.info(f"[handle_problem_category] Received callback data: {query.data}")
        
        # Handle category selection
        if query.data.startswith('cat_'):
            try:
                cat_idx = int(query.data.split('_')[1])
                if not (0 <= cat_idx < len(PROBLEM_CATEGORIES)):
                    raise ValueError(f"Invalid category index: {cat_idx}")
                
                category = PROBLEM_CATEGORIES[cat_idx]
                subcategories = PROBLEM_SUBCATEGORIES.get(category, [])
                
                if not subcategories:
                    # Store the subcategory and ask for problem description
                    if 'problems' not in context.user_data:
                        context.user_data['problems'] = []
                    
                    # Ensure we have enough problems in the list
                    current_problem_idx = context.user_data.get('current_problem_idx', 0)
                    while len(context.user_data['problems']) <= current_problem_idx:
                        context.user_data['problems'].append({})
                    
                    # Store the problem data
                    context.user_data['problems'][current_problem_idx] = {
                        'category': category,  # Store the main category
                        'type': category,       # For backward compatibility
                        'subtype': '',          # No subcategory
                        'subcategory': '',      # Also store in subcategory for clarity
                        'description': ''
                    }
                    return await ask_for_problem_description(update, context, 0)
                
                # Store selected category and show subcategories
                context.user_data['selected_category'] = category
                
                # Create keyboard for subcategories
                keyboard = []
                for i, subcategory in enumerate(subcategories):
                    keyboard.append([
                        InlineKeyboardButton(
                            subcategory,
                            callback_data=f"sub_{i}"
                        )
                    ])
                
                # Add back button
                keyboard.append([
                    InlineKeyboardButton("🔙 Back", callback_data="back_to_categories")
                ])
                
                # Store the category in the current problem
                current_problem_idx = context.user_data.get('current_problem_idx', 0)
                if 'problems' not in context.user_data:
                    context.user_data['problems'] = []
                while len(context.user_data['problems']) <= current_problem_idx:
                    context.user_data['problems'].append({})
                
                # Store category and subcategory in the problem data
                context.user_data['problems'][current_problem_idx]['category'] = category
                context.user_data['problems'][current_problem_idx]['type'] = category  # Also store in type for backward compatibility
                context.user_data['problems'][current_problem_idx]['subtype'] = ''  # Initialize subtype
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Update the message with subcategories
                await query.edit_message_text(
                    f"Category: {category}\n\n"
                    "Please select a subcategory:",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
                return PROBLEM_TYPE
                
            except (IndexError, ValueError) as e:
                logger.error(f"[handle_problem_category] Error processing category selection: {e}")
                await query.edit_message_text(
                    "⚠️ Error processing category. Please try again.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return ConversationHandler.END
        
        # Handle subcategory selection
        elif query.data.startswith('sub_'):
            try:
                sub_idx = int(query.data.split('_')[1])
                category = context.user_data.get('selected_category')
                
                if not category or category not in PROBLEM_SUBCATEGORIES:
                    raise ValueError("No category selected or invalid category")
                
                subcategories = PROBLEM_SUBCATEGORIES[category]
                
                if not (0 <= sub_idx < len(subcategories)):
                    raise ValueError(f"Invalid subcategory index: {sub_idx}")
                
                subcategory = subcategories[sub_idx]
                
                # Initialize problems list if not exists
                if 'problems' not in context.user_data:
                    context.user_data['problems'] = []
                
                # Add the problem with category and subcategory
                problem = {
                    'type': category,
                    'subtype': subcategory,
                    'category': category,  # Ensure category is set
                    'description': ''
                }
                
                # Check if this problem already exists
                if problem not in context.user_data['problems']:
                    context.user_data['problems'].append(problem)
                
                # Ask for problem description
                try:
                    return await ask_for_problem_description(update, context, len(context.user_data['problems']) - 1)
                except Exception as e:
                    logger.error(f"[handle_problem_category] Error in ask_for_problem_description: {e}")
                    await query.edit_message_text(
                        "⚠️ Error requesting problem description. Please try again.",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    return PROBLEM_CATEGORY
                
            except (IndexError, ValueError) as e:
                logger.error(f"[handle_problem_category] Error processing subcategory selection: {e}")
                await query.edit_message_text(
                    "⚠️ Error processing subcategory. Please try again.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return ConversationHandler.END
        
        # Handle back to categories
        elif query.data == "back_to_categories":
            # Show categories again
            keyboard = []
            for i, category in enumerate(PROBLEM_CATEGORIES):
                keyboard.append([
                    InlineKeyboardButton(
                        category,
                        callback_data=f"cat_{i}"
                    )
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "Please select a problem category:",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            return PROBLEM_TYPE
            
        else:
            logger.warning(f"[handle_problem_category] Unknown callback data: {query.data}")
            await query.answer("Invalid command. Please try again.", show_alert=True)
            return PROBLEM_TYPE
            
    except Exception as e:
        logger.error(f"[handle_problem_category] Unexpected error: {e}", exc_info=True)
        try:
            # Get language strings
            lang = context.user_data.get('language', 'en')
            strings = get_strings(lang)
            
            await query.edit_message_text(
                "⚠️ An unexpected error occurred. Please try again.",
                reply_markup=ReplyKeyboardRemove()
            )
        except:
            pass
        return ConversationHandler.END

async def ask_for_problem_description(update: Update, context: CallbackContext, problem_idx: int) -> int:
    """Ask user to describe the selected problem
    
    Args:
        update: Update object containing the callback query
        context: Callback context for the conversation
        problem_idx: Index of the current problem in the problems list
        
    Returns:
        int: Next conversation state (PROBLEM_DESCRIPTION)
    """
    try:
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        if 'problems' not in context.user_data or problem_idx >= len(context.user_data['problems']):
            logger.error("Invalid problem index or problems list")
            return ConversationHandler.END
            
        problem = context.user_data['problems'][problem_idx]
        context.user_data['current_problem_idx'] = problem_idx
        
        # Get context text
        selected_sections = context.user_data.get('work_sections', [])
        selected_servers = context.user_data.get('servers', [])
        
        context_text = []
        if selected_sections:
            context_text.append(f"✅ Selected Sections: {', '.join(selected_sections)}")
        if selected_servers:
            context_text.append(f"🖥️ Selected Servers: {', '.join(selected_servers)}")
        context_str = '\n'.join(context_text) + '\n\n' if context_text else ''
        
        # Format problem info
        problem_type = problem['type']
        subtype = problem.get('subtype', '')
        
        if subtype:
            problem_info = f"🔧 Issue with {problem_type} > {subtype}"
        else:
            problem_info = f"🔧 Issue with {problem_type}"
        
        # Add problem number if there are multiple problems
        if len(context.user_data['problems']) > 1:
            problem_info += f" ({problem_idx + 1}/{len(context.user_data['problems'])})"
        
        # Check if this is a live event problem
        is_live_event = (problem_type == "Broadcast" and subtype in ["Live Streams", "Live Broadcast"]) or \
                       (problem_type == "Live Source") or \
                       (problem_type == "Live Broadcast") or \
                       (problem_type == "Live Event") or \
                       (subtype and "Live" in subtype)
        
        if is_live_event:
            # For live events, ask for event name first
            context.user_data['awaiting_live_event_name'] = True
            
            if update.callback_query:
                try:
                    await update.callback_query.edit_message_text(
                        f"{context_str}{problem_info}\n\n"
                        "📝 Program Name:",
                        reply_markup=InlineKeyboardMarkup([[]]),  # Empty inline keyboard
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.error(f"[ask_for_problem_description] Error editing message: {e}")
                    await update.callback_query.message.reply_text(
                        f"{context_str}{problem_info}\n\n"
                        "📝 Program Name:",
                        reply_markup=ReplyKeyboardRemove()
                    )
            else:
                await update.message.reply_text(
                    f"{context_str}{problem_info}\n\n"
                    "📝 Program Name:",
                    reply_markup=ReplyKeyboardRemove()
                )
            
            return LIVE_EVENT_NAME
        else:
            # For regular problems, ask for description directly
            context.user_data['awaiting_live_event_name'] = False
            
            try:
                if update.callback_query:
                    try:
                        await update.callback_query.edit_message_text(
                            f"{context_str}{problem_info}\n\n"
                            "📝 Describe the issue:",
                            reply_markup=InlineKeyboardMarkup([[]]),  # Empty inline keyboard
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except Exception as e:
                        logger.error(f"[ask_for_problem_description] Error editing message: {e}")
                        await update.callback_query.message.reply_text(
                            f"{context_str}{problem_info}\n\n"
                            "📝 Describe the issue:",
                            reply_markup=ReplyKeyboardRemove()
                        )
                else:
                    await update.message.reply_text(
                        f"{context_str}{problem_info}\n\n"
                        "📝 Describe the issue:",
                        reply_markup=ReplyKeyboardRemove()
                    )
                
                # Return the next state
                return PROBLEM_DESCRIPTION
                
            except Exception as e:
                logger.error(f"[ask_for_problem_description] Error in regular problem flow: {e}")
                if update.callback_query and update.callback_query.message:
                    await update.callback_query.message.reply_text(
                        "⚠️ Error requesting problem description. Please try again.",
                        reply_markup=ReplyKeyboardRemove()
                    )
                return PROBLEM_CATEGORY
            
            return PROBLEM_DESCRIPTION
            
    except Exception as e:
        logger.error(f"[ask_for_problem_description] Unexpected error: {e}", exc_info=True)
        try:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    "⚠️ An unexpected error occurred. Please try again.",
                    reply_markup=ReplyKeyboardRemove()
                )
            else:
                await update.message.reply_text(
                    "⚠️ An unexpected error occurred. Please try again.",
                    reply_markup=ReplyKeyboardRemove()
                )
        except:
            pass
        return ConversationHandler.END
            
    except Exception as e:
        logger.critical(f"[handle_problem_type] Unexpected error: {e}", exc_info=True)
        try:
            if 'query' in locals():
                await query.edit_message_text(
                    "⚠️ خطای غیرمنتظره‌ای رخ داد. لطفاً دوباره تلاش کنید.",
                    reply_markup=ReplyKeyboardRemove()
                )
            else:
                # If we can't edit the message, try to send a new one
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="⚠️ خطای غیرمنتظره‌ای رخ داد. لطفاً دوباره تلاش کنید.",
                    reply_markup=ReplyKeyboardRemove()
                )
        except Exception as send_error:
            logger.error(f"[handle_problem_type] Failed to send error message: {send_error}")
            
        return ConversationHandler.END

async def handle_live_event_name(update: Update, context: CallbackContext) -> int:
    """Get live event name for the current problem"""
    try:
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        live_event_name = update.message.text.strip()
        if not live_event_name:
            await update.message.reply_text(
                "⚠️ Live program name cannot be empty. Please enter it again:"
            )
            return LIVE_EVENT_NAME
        
        # Get current problem index and problems list
        current_idx = context.user_data.get('current_problem_idx', 0)
        problems = context.user_data.get('problems', [])
        
        if not problems or current_idx >= len(problems):
            logger.error("Invalid problem index or empty problems list")
            return await ask_for_rating(update, context)
        
        # Store live event name with the current problem
        if 'live_events' not in context.user_data:
            context.user_data['live_events'] = {}
        if str(current_idx) not in context.user_data['live_events']:
            context.user_data['live_events'][str(current_idx)] = {}
            
        context.user_data['live_events'][str(current_idx)]['name'] = live_event_name
        
        # Also store directly in the problem object for easier access
        if current_idx < len(problems):
            problems[current_idx]['live_event_name'] = live_event_name
            # Save back to user_data
            context.user_data['problems'] = problems
        
        # Create keyboard for selecting the source of the problem
        keyboard = [
            [InlineKeyboardButton(src, callback_data=f"src_{i}")] 
            for i, src in enumerate(LIVE_EVENT_SOURCES)
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Get context text
        selected_sections = context.user_data.get('work_sections', [])
        selected_servers = context.user_data.get('servers', [])
        
        context_text = []
        if selected_sections:
            context_text.append(f"✅ Selected Sections: {', '.join(selected_sections)}")
        if selected_servers:
            context_text.append(f"🖥️ Selected Servers: {', '.join(selected_servers)}")
        context_str = '\n'.join(context_text) + '\n\n' if context_text else ''
        
        # Store that we're waiting for live event source
        context.user_data['awaiting_live_event_source'] = True
        
        # Ensure we have all the problem data in the right format
        if current_idx < len(problems):
            if 'live_events' not in problems[current_idx]:
                problems[current_idx]['live_events'] = {}
            problems[current_idx]['live_events']['name'] = live_event_name
            context.user_data['problems'] = problems  # Save back to user_data
        
        # Send the message with the source selection keyboard
        message = await update.message.reply_text(
            f"{context_str}"
            f"📺 Live Program: {live_event_name}\n\n"
            f"🔍Source of the issue ({current_idx + 1}/{len(problems)}):",
            reply_markup=reply_markup
        )
        
        # Store the message ID for later reference
        context.user_data['last_message_id'] = message.message_id
        
        # Explicitly return the next state
        return LIVE_EVENT_SOURCE
        
    except Exception as e:
        logger.error(f"Error processing live program name: {e}", exc_info=True)
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        await update.message.reply_text(
            "⚠️ An error occurred while processing the live program name. Please try again."
        )
        return LIVE_EVENT_NAME

async def handle_live_event_source_fallback(update: Update, context: CallbackContext) -> int:
    """Handle case when user sends text instead of using the inline keyboard for live event source"""
    try:
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        await update.message.reply_text(
            "⚠️ Please select one of the issue source options from the keyboard."
        )
        return LIVE_EVENT_SOURCE
    except Exception as e:
        logger.error(f"Error in handle_live_event_source_fallback: {e}", exc_info=True)
        return LIVE_EVENT_SOURCE

async def handle_live_event_source(update: Update, context: CallbackContext) -> int:
    """Get the source of the live event issue for the current problem"""
    try:
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        if not update.callback_query:
            logger.error("[handle_live_event_source] No callback_query in update")
            return ConversationHandler.END
            
        query = update.callback_query
        await query.answer()
        
        try:
            # Get current problem index and problems list
            current_idx = context.user_data.get('current_problem_idx', 0)
            problems = context.user_data.get('problems', [])
            
            if not problems or current_idx >= len(problems):
                logger.error("Invalid problem index or empty problems list")
                return await ask_for_rating(update, context)
            
            # Get source from callback data
            src_idx = int(query.data.split('_')[1])
            if not (0 <= src_idx < len(LIVE_EVENT_SOURCES)):
                raise ValueError(f"Invalid source index: {src_idx}")
                
            source = LIVE_EVENT_SOURCES[src_idx]
            
            # Store source with the current problem
            if 'live_events' not in context.user_data:
                context.user_data['live_events'] = {}
            if str(current_idx) not in context.user_data['live_events']:
                context.user_data['live_events'][str(current_idx)] = {}
                
            # Store the source in live_events
            context.user_data['live_events'][str(current_idx)]['source'] = source
            
            # Also store directly in the problem object for easier access
            if current_idx < len(problems):
                problems[current_idx]['live_event_source'] = source
                # If we have the name from previous steps, store that too
                if 'name' in context.user_data['live_events'][str(current_idx)]:
                    problems[current_idx]['live_event_name'] = context.user_data['live_events'][str(current_idx)]['name']
            
            # Get context text
            selected_sections = context.user_data.get('work_sections', [])
            selected_servers = context.user_data.get('servers', [])
            
            context_text = []
            if selected_sections:
                context_text.append(f"✅ Selected Sections: {', '.join(selected_sections)}")
            if selected_servers:
                context_text.append(f"🖥️ Selected Servers: {', '.join(selected_servers)}")
            context_str = '\n'.join(context_text) + '\n\n' if context_text else ''
            
            # Clear the awaiting flag
            if 'awaiting_live_event_source' in context.user_data:
                del context.user_data['awaiting_live_event_source']
            
            # Update the current problem with the event info
            problems = context.user_data.get('problems', [])
            if current_idx < len(problems):
                if 'live_events' not in context.user_data:
                    context.user_data['live_events'] = {}
                if str(current_idx) not in context.user_data['live_events']:
                    context.user_data['live_events'][str(current_idx)] = {}
                
                # Ensure we have the latest source and name in the problem object
                context.user_data['live_events'][str(current_idx)]['source'] = source
                problems[current_idx]['live_event_source'] = source
                
                # If we have the name from previous steps, store that too
                if 'name' in context.user_data['live_events'][str(current_idx)]:
                    problems[current_idx]['live_event_name'] = context.user_data['live_events'][str(current_idx)]['name']
                
                context.user_data['current_problem_idx'] = current_idx
                context.user_data['problems'] = problems  # Save back to user_data
            
            try:
                # Get the live event name with a fallback
                live_event_name = context.user_data['live_events'][str(current_idx)].get('name', 'Unnamed Event')
                
                # Try to edit the existing message
                await query.edit_message_text(
                    f"{context_str}"
                    f"📺 Live Program: {live_event_name}\n"
                    f"🔍 Issue Source: {source}\n\n"
                    f"📝 Describe the issue ({current_idx + 1}/{len(problems)})",
                    reply_markup=None  # Remove inline keyboard
                )
                
                # Return the next state
                return PROBLEM_DESCRIPTION
                
            except Exception as edit_error:
                logger.error(f"[handle_live_event_source] Error editing message: {edit_error}")
                # Fallback: Send new message if edit fails
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"{context_str}"
                         f"📺 Live Program: {live_event_name}\n"
                         f"🔍 Issue Source: {source}\n\n"
                         f"📝 Describe the issue ({current_idx + 1}/{len(problems)})",
                    reply_markup=ReplyKeyboardRemove()
                )
                # Return the next state
                return PROBLEM_DESCRIPTION
                
        except (IndexError, ValueError) as e:
            logger.error(f"[handle_live_event_source] Error processing source: {e}", exc_info=True)
            await query.edit_message_text(
                "⚠️ An error occurred while processing the live event source. Please try again.",
                reply_markup=None
            )
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"[handle_live_event_source] Unexpected error: {e}", exc_info=True)
        try:
            # Get language strings
            lang = context.user_data.get('language', 'en')
            strings = get_strings(lang)
            
            if 'query' in locals():
                await query.edit_message_text(
                    "⚠️ An unexpected error occurred. Please try again.",
                    reply_markup=None
                )
            else:
                await update.message.reply_text(
                    "⚠️ An unexpected error occurred. Please try again.",
                    reply_markup=ReplyKeyboardRemove()
                )
        except Exception as send_error:
            logger.error(f"[handle_live_event_source] Failed to send error message: {send_error}")
        return ConversationHandler.END

async def handle_problem_description(update: Update, context: CallbackContext) -> int:
    """Get problem description for each selected problem"""
    try:
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        problem_description = update.message.text.strip()
        if not problem_description:
            await update.message.reply_text("⚠️ Problem description cannot be empty. Please try again:")
            return PROBLEM_DESCRIPTION
        
        # Ensure problems list exists
        if 'problems' not in context.user_data:
            context.user_data['problems'] = []
            
        current_problem_idx = context.user_data.get('current_problem_idx', 0)
        
        # If we don't have a problem at this index yet, create one
        while len(context.user_data['problems']) <= current_problem_idx:
            context.user_data['problems'].append({
                'type': 'Unspecified',
                'category': 'General',
                'description': '',
                'subtype': ''
            })
            
        # Update the current problem's description
        current_problem = context.user_data['problems'][current_problem_idx]
        current_problem['description'] = problem_description
        
        # Ensure required fields are set
        if 'type' not in current_problem or not current_problem['type']:
            current_problem['type'] = current_problem.get('category', 'General')
        if 'category' not in current_problem or not current_problem['category']:
            current_problem['category'] = current_problem.get('type', 'General')
        
        # Ask if there are more problems
        keyboard = [
            [InlineKeyboardButton("✅ Yes", callback_data="more_problems_yes")],
            [InlineKeyboardButton("❌ No", callback_data="more_problems_no")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "Is there another issue you'd like to report?",
            reply_markup=reply_markup
        )
        
        return ASK_MORE_PROBLEMS
        
    except Exception as e:
        logger.error(f"[handle_problem_description] Error: {e}", exc_info=True)
        await update.message.reply_text(
            "⚠️ An error occurred while saving the problem description. Please try again.",
            reply_markup=ReplyKeyboardRemove()
        )
        return PROBLEM_DESCRIPTION
        
        # Update current problem's description
        problems[current_idx]['description'] = problem_description
        
        # Check if there are more problems that need descriptions
        next_problem = next(
            (i for i, p in enumerate(problems) if not p.get('description')),
            None
        )
        
        # Get context text for next message
        selected_sections = context.user_data.get('work_sections', [])
        selected_servers = context.user_data.get('servers', [])
        
        context_text = []
        if selected_sections:
            context_text.append(f"✅ Selected Sections: {', '.join(selected_sections)}")
        if selected_servers:
            context_text.append(f"🖥️ Selected Servers: {', '.join(selected_servers)}")
        context_str = '\n'.join(context_text) + '\n\n' if context_text else ''
        
        if next_problem is not None:
            # Move to next problem that needs description
            context.user_data['current_problem_idx'] = next_problem
            problem = problems[next_problem]
            
            if problem['type'] == "Live events":
                # If this is a Live Event problem, ask for event name first
                prompt_text = (
                    f"{context_str}"
                    f"🔴 Issue with Live Event ({next_problem + 1}/{len(problems)})\n\n"
                    "📝 Program Name:"
                )
                
                await update.message.reply_text(
                    "✅ Previous problem description saved successfully.\n\n" + prompt_text,
                    reply_markup=ReplyKeyboardRemove()
                )
                return LIVE_EVENT_NAME
            else:
                # For other problem types, ask for description
                lang = context.user_data.get('language', 'en')
                strings = get_strings(lang)
                prompt_text = (
                    f"{context_str}"
                    f"🔧 {strings.get('problem_description', 'Problem Description')} ({next_problem + 1}/{len(problems)})\n\n"
                    f"{strings.get('please_describe', 'Please describe the issue in detail:')}"
                )
                
                await update.message.reply_text(
                    f"✅ {strings.get('previous_description_saved', 'Previous description saved successfully')}\n\n" + prompt_text,
                    reply_markup=ReplyKeyboardRemove()
                )
                return PROBLEM_DESCRIPTION
        else:
            # All problems have descriptions, show summary and move to rating
            try:
                # Create a summary of all reported problems
                problems_summary = []
                for i, problem in enumerate(problems, 1):
                    problem_type = problem.get('type', 'Unknown')
                    problem_desc = problem.get('description', 'No description')
                    
                    # Add live event details if available
                    if problem_type == 'Live events' and 'live_events' in context.user_data:
                        live_event = context.user_data['live_events'].get(str(i-1), {})
                        if live_event:
                            problem_type += f" ({live_event.get('name', 'Unnamed')} - {live_event.get('source', 'Unknown source')})"
                    
                    # Truncate long descriptions for the summary
                    if len(problem_desc) > 50:
                        problem_desc = problem_desc[:47] + '...'
                    
                    problems_summary.append(f"{i}. {problem_type}: {problem_desc}")
                
                # Send summary to user
                summary_text = "\n\n".join(problems_summary)
                await update.message.reply_text(
                    f"✅ All issues have been successfully recorded.\n\n"
                    f"📋 *Summary of Reported Issues:*\n{summary_text}\n\n"
                    "Next, please rate your performance for today.",
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode='Markdown'
                )
                
                # Move to rating
                return await ask_for_rating(update, context)
                
            except Exception as summary_error:
                logger.error(f"Error showing problems summary: {summary_error}", exc_info=True)
                # If there's an error showing summary, continue to rating anyway
                return await ask_for_rating(update, context)
        
    except Exception as e:
        logger.error(f"Error processing problem description: {e}", exc_info=True)
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        await update.message.reply_text(
            "⚠️ An error occurred while saving the description. Please enter the description again:",
            reply_markup=ReplyKeyboardRemove()
        )
        return PROBLEM_DESCRIPTION

async def handle_more_problems(update: Update, context: CallbackContext) -> int:
    """Handle user response when asked if they have more problems"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        if query.data == "more_problems_yes":
            # Increment the problem index for the next problem
            current_idx = context.user_data.get('current_problem_idx', 0)
            context.user_data['current_problem_idx'] = current_idx + 1
            
            # Show problem categories again
            keyboard = []
            for i, category in enumerate(PROBLEM_CATEGORIES):
                # Get localized category name if available
                category_key = category.lower().replace(' ', '_')
                display_name = strings.get(f'category_{category_key}', category)
                
                keyboard.append([
                    InlineKeyboardButton(
                        display_name,
                        callback_data=f"cat_{i}"
                    )
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "Please select the category for the next issue:",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            return PROBLEM_CATEGORY
            
        elif query.data == "more_problems_no":
            # No more problems, move to rating
            # Make sure we have at least one problem if user said they had problems
            if 'problems' not in context.user_data or not context.user_data['problems']:
                # If no problems were added, add a default one
                if 'problems' not in context.user_data:
                    context.user_data['problems'] = []
                
                context.user_data['problems'].append({
                    'type': 'General',
                    'category': 'General',
                    'description': 'No description',
                    'subtype': ''
                })
            
            # Reset current problem index
            context.user_data['current_problem_idx'] = 0
            
            keyboard = [
                [InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(1, 6)],
                [InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(6, 11)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "Rate your performance today on a scale from 1 to 10:",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            return RATING
            
    except Exception as e:
        logger.error(f"[handle_more_problems] Error: {e}", exc_info=True)
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        await query.edit_message_text(
            "⚠️ An error occurred while processing your response. Please try again.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

async def ask_for_rating(update: Update, context: CallbackContext) -> int:
    """Ask the user to rate their work
    
    Args:
        update: Update object containing the message or callback query
        context: Callback context for the conversation
        
    Returns:
        int: Next conversation state (RATING)
    """
    try:
        # Create rating keyboard
        keyboard = [
            [InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(1, 6)],
            [InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(6, 11)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        # Send or edit the message with the rating prompt
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "Rate your performance today on a scale from 1 to 10:",
                reply_markup=reply_markup
            )
        elif update.message:
            await update.message.reply_text(
                "Rate your performance today on a scale from 1 to 10:",
                reply_markup=reply_markup
            )
        else:
            logger.error("[ask_for_rating] No valid message or query in update")
            return ConversationHandler.END
            
        return RATING
        
    except Exception as e:
        logger.error(f"[ask_for_rating] Error: {e}", exc_info=True)
        try:
            # Get language strings
            lang = context.user_data.get('language', 'en')
            strings = get_strings(lang)
            
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    "⚠️ An error occurred while displaying the rating options. Please try again.",
                    reply_markup=ReplyKeyboardRemove()
                )
            elif update.message:
                await update.message.reply_text(
                    "⚠️ An error occurred while displaying the rating options. Please try again.",
                    reply_markup=ReplyKeyboardRemove()
                )
        except:
            pass
        return ConversationHandler.END

async def handle_document(update: Update, context: CallbackContext) -> int:
    """Process uploaded documents
    
    Args:
        update: Update object containing the document
        context: Callback context for the conversation
        
    Returns:
        int: Next conversation state or DOCUMENT_UPLOAD on error
    """
    # Get language strings
    lang = context.user_data.get('language', 'en')
    strings = get_strings(lang)
    
    if not update.message or not update.message.document:
        await update.message.reply_text("⚠️ Please send a valid file.")
        return DOCUMENT_UPLOAD
        
    document = update.message.document
    file_id = document.file_id
    
    # Validate file name
    file_name = (document.file_name or f"document_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin")
    
    # Security: Sanitize file name
    file_name = "".join(c for c in file_name if c.isalnum() or c in '._- ').strip()
    if not file_name:
        file_name = f"document_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"
    
    # Security: Set maximum file size (10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    if document.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            f"⚠️ File size ({document.file_size / (1024*1024):.1f} MB) exceeds the maximum allowed (10 MB)."
        )
        return DOCUMENT_UPLOAD
    
    # Security: Allowed file types (whitelist approach)
    ALLOWED_EXTENSIONS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.jpg', '.jpeg', '.png'}
    file_ext = os.path.splitext(file_name)[1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        await update.message.reply_text(
            f"⚠️ File extension not allowed. Please upload a file with one of these formats:\n"
            f"{', '.join(ALLOWED_EXTENSIONS)}"
        )
        return DOCUMENT_UPLOAD
    
    try:
        # Get the file
        file = await context.bot.get_file(file_id)
        
        # Create documents directory if it doesn't exist
        os.makedirs("documents", exist_ok=True)
        
        # Save file with a unique name
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(hash(f"{file_id}_{timestamp}"))[:8]
        file_path = os.path.join("documents", f"{timestamp}_{unique_id}_{file_name}")
        
        # Download the file
        await file.download_to_drive(file_path)
        
        # Store file information in user data
        if 'documents' not in context.user_data:
            context.user_data['documents'] = []
            
        file_info = {
            'file_id': file_id,
            'file_name': file_name,
            'file_path': file_path,
            'file_size': document.file_size,
            'mime_type': document.mime_type,
            'upload_time': datetime.now().isoformat()
        }
        context.user_data['documents'].append(file_info)
        
        # Log file information (without sensitive data)
        logger.info(
            f"New file uploaded: {file_name} "
            f"({document.file_size} bytes, {file_ext})"
        )
        
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        await update.message.reply_text(
            f"✅ File received successfully.\n"
            f"📄 File name: {file_name}\n"
            f"📊 Size: {document.file_size / 1024:.1f} KB"
        )
        
        # Prepare rating question
        keyboard = [
            [InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(1, 6)],
            [InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(6, 11)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await update.message.reply_text(
                "✅ File received successfully.\n\n"
                "Rate your performance today on a scale from 1 to 10:",
                reply_markup=reply_markup
            )
            return RATING
        except Exception as e:
            logger.error(f"Error sending rating question: {e}")
            await update.message.reply_text(
                "⚠️ An error occurred while displaying the rating question. Please try again."
            )
            return DOCUMENT_UPLOAD
        
    except Exception as e:
        logger.error(f"Error processing file: {e}", exc_info=True)
        
        # Delete file in case of error
        if 'file_path' in locals() and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as cleanup_error:
                logger.error(f"Error deleting corrupted file: {cleanup_error}")
        
        await update.message.reply_text(
            "⚠️ An error occurred while processing the file. Please try again."
        )
        return DOCUMENT_UPLOAD

def save_to_json(report_data: dict, report_id: str = None) -> tuple:
    """Save report to JSON file
    
    Args:
        report_data: Dictionary containing report information
        report_id: Report ID for update (if exists)
        
    Returns:
        tuple: (Path to saved file, report ID)
    """
    try:
        # Create reports directory if it doesn't exist
        reports_dir = Path('reports')
        reports_dir.mkdir(exist_ok=True)
        
        # Path to main JSON file - using relative path to the Analytics folder in the parent directory
        analytics_dir = Path(__file__).parent.parent / 'Analytics'
        analytics_dir.mkdir(parents=True, exist_ok=True)
        main_json_file = analytics_dir / 'Daily_reports.json'
        
        # Read existing reports from main file
        reports = []
        if main_json_file.exists():
            try:
                with open(main_json_file, 'r', encoding='utf-8') as f:
                    reports = json.load(f)
                if not isinstance(reports, list):
                    reports = []
            except json.JSONDecodeError:
                reports = []
        
        # Create a copy of report data to prevent unwanted modifications
        report_data = report_data.copy()
        
        # Ensure proper problem categories are saved
        if 'problems' in report_data and report_data['problems']:
            for problem in report_data['problems']:
                if 'type' not in problem:
                    problem['type'] = 'Other'  # Default value for problem type
                # Ensure required fields exist
                if 'description' not in problem:
                    problem['description'] = 'No description'
        
        # Create or update report
        report_entry = None
        report_index = -1
        
        if report_id:
            # Find existing report
            for idx, report in enumerate(reports):
                if report.get('id') == report_id:
                    report_entry = report
                    report_index = idx
                    break
        
        if not report_entry:
            # Create new report
            report_id = str(uuid.uuid4())
            report_entry = {
                'id': report_id,
                'timestamp': datetime.now().isoformat(),
                'data': report_data,
                'status': 'pending',
                'manager_feedback': None,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            reports.append(report_entry)
        else:
            # Update existing report
            report_entry['data'].update({
                'problems': report_data.get('problems', []),
                'employee': report_data.get('employee'),
                'work_sections': report_data.get('work_sections', []),
                'servers': report_data.get('servers', []),
                'additional_info': report_data.get('additional_info', '')
            })
            report_entry['updated_at'] = datetime.now().isoformat()
            report_id = report_entry['id']
        
        # Save all reports to the main file
        with open(main_json_file, 'w', encoding='utf-8') as f:
            json.dump(reports, f, ensure_ascii=False, indent=2, default=str)
            
        return str(main_json_file.absolute()), report_id
        
    except Exception as e:
        logger.error(f'Error saving JSON report: {e}', exc_info=True)
        raise
        raise

async def finish_report(update: Update, context: CallbackContext) -> int:
    """Finalize and submit the report"""
    user = update.effective_user
    current_user_data = context.user_data
    
    # Get language strings
    lang = current_user_data.get('language', 'en')
    strings = get_strings(lang)
    
    # Determine update type (message or callback query)
    is_callback = update.callback_query is not None
    message = update.callback_query.message if is_callback else update.message
    
    try:
        # First, prepare the report data with all necessary fields
        report_data = current_user_data.copy()
        
        # Ensure all necessary data is included in the report data
        if 'problems' in current_user_data and current_user_data['problems']:
            # Create a deep copy of problems to avoid modifying the original
            report_data['problems'] = []
            
            # Filter out any empty problems or category headers
            for i, problem in enumerate(current_user_data['problems']):
                # Skip empty problems or category headers
                if not problem.get('description') and not problem.get('subtype'):
                    continue
                    
                # Create a new problem dict with all the data
                new_problem = problem.copy()
                
                # Ensure we have required fields
                if 'type' not in new_problem and 'category' in new_problem:
                    new_problem['type'] = new_problem['category']
                if 'subtype' not in new_problem and 'subcategory' in new_problem:
                    new_problem['subtype'] = new_problem['subcategory']
                
                # Skip if this is just a category header
                if new_problem.get('type') in PROBLEM_CATEGORIES and not new_problem.get('subtype'):
                    continue
                
                # Handle live event data if this is a live event problem
                is_live_event = (
                    new_problem.get('type') in ['پخش زنده', 'Live Event', 'Live events'] or 
                    new_problem.get('category') in ['پخش زنده', 'Live Event', 'Live events'] or
                    new_problem.get('subtype') in ['پخش زنده', 'Live Event', 'Live events']
                )
                
                if is_live_event:
                    # First check if live event data is already in the problem
                    if 'live_event_name' not in new_problem or 'live_event_source' not in new_problem:
                        # Try to get from live_events dictionary with string key
                        if 'live_events' in current_user_data and str(i) in current_user_data['live_events']:
                            live_event = current_user_data['live_events'][str(i)]
                            new_problem['live_event_name'] = live_event.get('name', 'Unspecified')
                            new_problem['live_event_source'] = live_event.get('source', 'Unspecified')
                        # Then check with integer key (for backward compatibility)
                        elif 'live_events' in current_user_data and i in current_user_data['live_events']:
                            live_event = current_user_data['live_events'][i]
                            new_problem['live_event_name'] = live_event.get('name', 'Unspecified')
                            new_problem['live_event_source'] = live_event.get('source', 'Unspecified')
                        # If no live event data found, set default values
                        else:
                            new_problem['live_event_name'] = 'Unspecified'
                            new_problem['live_event_source'] = 'Unspecified'
                
                report_data['problems'].append(new_problem)
        
        # Include live events in the report data if they exist
        if 'live_events' in current_user_data:
            report_data['live_events'] = current_user_data['live_events']
            
        # Now generate the report text using the prepared data
        report_text = format_report(report_data)
        
        # Escape special characters for MarkdownV2
        try:
            safe_report_text = escape_markdown(report_text, version=2)
        except Exception as e:
            logger.error(f"Failed to escape markdown: {e}")
            safe_report_text = report_text  # Fallback to original text if escaping fails
        
        # Save to JSON (Excel will be saved later in save_manager_feedback)
        json_file_path, report_id = save_to_json(report_data)
        current_user_data['report_id'] = report_id
        
        # Save a copy of the data for use in save_manager_feedback
        current_user_data['report_data'] = report_data.copy()
        
        # Convert path to Path object to check file existence
        json_file = Path(json_file_path)
        
    except Exception as e:
        logger.error(f"Error processing report: {e}", exc_info=True)
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="❌ An error occurred while processing the report. Please try again."
        )
        return ConversationHandler.END
    
    # Send report to admin
    try:
        # ارسال مستندات (در صورت وجود)
        if 'documents' in current_user_data and current_user_data['documents']:
            for doc_info in current_user_data['documents']:
                if os.path.exists(doc_info['file_path']):
                    with open(doc_info['file_path'], 'rb') as doc_file:
                        # Escape special characters in the caption
                        employee_name = current_user_data.get("employee", "User")
                        safe_employee_name = ''.join(['\\' + c if c in r'\_*[]()~`>#+-=|{}.!' else c for c in str(employee_name)])
                        safe_file_name = ''.join(['\\' + c if c in r'\_*[]()~`>#+-=|{}.!' else c for c in str(doc_info["file_name"])])
                        
                        await context.bot.send_document(
                            chat_id=ADMIN_CHAT_ID,
                            document=doc_file,
                            filename=doc_info['file_name'],  # Send original filename
                            caption=f'📄 Document from {safe_employee_name}: {safe_file_name}',
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                else:
                    logger.warning(f"Document file not found at path: {doc_info['file_path']}")
        
        # Create report approval button
        keyboard = [
            [InlineKeyboardButton("✅ Approve Report", callback_data=f"approve_{report_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send report with approval button
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=safe_report_text,  # Use the escaped text
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        
        # Send report summary to user
        try:
            # Create a safe version of the user report text (without the first line)
            try:
                user_report_text = "📋 *Your Report Summary:*\n\n"
                if '\n' in safe_report_text:
                    user_report_text += safe_report_text.split('\n', 1)[1]
                else:
                    user_report_text = safe_report_text
            except Exception as e:
                logger.error(f"Error preparing user report text: {e}")
                user_report_text = "📋 Your report has been submitted successfully."
            
            # ارسال به کاربر
            if is_callback:
                try:
                    await update.callback_query.edit_message_text(
                        text=user_report_text,
                        parse_mode=ParseMode.MARKDOWN_V2,
                        reply_markup=None
                    )
                except Exception as edit_error:
                    logger.error(f"Error editing user message: {edit_error}")
                    await context.bot.send_message(
                        chat_id=update.effective_user.id,
                        text=user_report_text,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
            else:
                await context.bot.send_message(
                    chat_id=update.effective_user.id,
                    text=user_report_text,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            
            # Send final confirmation message
            success_message = (
                '✅ Your report has been submitted successfully. Thank you!\n'
            )
            
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=success_message,
            )
            
        except Exception as user_report_error:
            logger.error(f"Error sending report to user: {user_report_error}")
            # In case of error, at least send the confirmation message
            success_message = (
                '✅ Your report has been submitted successfully. Thank you!\n'
            )
            
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=success_message,
            )
    except Exception as e:
        logger.error(f"Failed to send report to admin: {e}")
        
        # Send success message to user
        success_message = (
            '✅ Your report has been submitted successfully. Thank you!\n'
        )
        
        try:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=success_message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Failed to send success message: {e}")
            # Try one more time with a simpler message
            try:
                await context.bot.send_message(
                    chat_id=update.effective_user.id,
                    text='✅ Your report has been submitted successfully.'
                )
            except Exception as e2:
                logger.error(f"Failed to send fallback success message: {e2}")
        
        # Clear temporary user data
        try:
            context.user_data.clear()
        except Exception as e:
            logger.error(f"Error clearing user data: {e}")
        
        return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext) -> int:
    """Cancel the current operation"""
    # Get language strings
    lang = context.user_data.get('language', 'en')
    strings = get_strings(lang)
    
    await update.message.reply_text(
        'Operation cancelled. Use /start to begin again.',
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    return ConversationHandler.END


async def check_reports(update: Update, context: CallbackContext) -> int:
    """Check who has reported between 9 AM and 3 AM"""
    try:
        # Get current date and time
        now = datetime.now()
        today = now.date()
        
        # Define time range (9 AM to 3 AM next day)
        start_time = datetime.combine(today, datetime.strptime('09:00', '%H:%M').time())
        end_time = datetime.combine(today + timedelta(days=1), datetime.strptime('03:00', '%H:%M').time())
        
        # If current time is between 12 AM and 3 AM, adjust the date range
        if now.hour < 3:
            start_time -= timedelta(days=1)
        
        # Load all reports
        analytics_dir = Path(__file__).parent.parent / 'Analytics'
        reports_file = analytics_dir / 'Daily_reports.json'
        
        if not reports_file.exists():
            await update.message.reply_text("No reports found. The bot is looking in: " + str(reports_file))
            return ConversationHandler.END
            
        with open(reports_file, 'r', encoding='utf-8') as f:
            reports = json.load(f)
        
        # Get all employees
        employees = {}
        for emp in load_employees():
            name = emp['data']['name']
            employees[name] = False  # Initially mark as not reported
        
        # Check who has reported in the time range
        reported_employees = set()
        for report in reports:
            try:
                report_time = datetime.fromisoformat(report['timestamp'])
                if start_time <= report_time < end_time:
                    # Extract employee name (format is usually "NAME - Department (Hours)")
                    employee_name = report['data']['employee'].split(' - ')[0].strip()
                    reported_employees.add(employee_name)
            except (KeyError, IndexError, ValueError) as e:
                logger.error(f"Error processing report: {e}")
                continue
        
        # Prepare the response
        response = []
        response.append("📋 *Daily Report Status (9 AM - 3 AM)*\n")
        
        # Get list of all employee names
        all_employees = set(employees.keys())
        
        # Add reported employees
        response.append("✅ *Reported:*\n" + "\n".join(sorted(reported_employees)) + "\n")
        
        # Add missing employees
        missing = all_employees - reported_employees
        response.append("\n❌ *Not Reported:*\n" + "\n".join(sorted(missing)) if missing else "\n🎉 *All employees have reported!*")
        
        # Send the response
        await update.message.reply_markdown("\n".join(response))
        
    except Exception as e:
        logger.error(f"Error in check_reports: {e}", exc_info=True)
        await update.message.reply_text("An error occurred while checking reports. Please try again later.")
    
    return ConversationHandler.END


async def get_monthly_reports(month: int, year: int) -> dict:
    """
    Get reports count by employee for a specific month and year
    
    Args:
        month: Month number (1-12)
        year: Year (e.g., 2023)
        
    Returns:
        dict: Dictionary with employee names as keys and report counts as values
    """
    try:
        # Load all reports
        analytics_dir = Path(__file__).parent.parent / 'Analytics'
        reports_file = analytics_dir / 'Daily_reports.json'
        
        if not reports_file.exists():
            return {}
            
        with open(reports_file, 'r', encoding='utf-8') as f:
            reports = json.load(f)
        
        # Initialize employee counts
        employee_counts = {}
        
        # Process each report
        for report in reports:
            try:
                report_date = datetime.fromisoformat(report['timestamp'])
                
                # Check if report is in the target month and year
                if report_date.month == month and report_date.year == year:
                    # Extract employee name (format is usually "NAME - Department (Hours)")
                    employee_name = report['data']['employee'].split(' - ')[0].strip()
                    
                    # Update count for this employee
                    if employee_name in employee_counts:
                        employee_counts[employee_name] += 1
                    else:
                        employee_counts[employee_name] = 1
                        
            except (KeyError, IndexError, ValueError) as e:
                logger.error(f"Error processing report: {e}")
                continue
                
        return employee_counts
        
    except Exception as e:
        logger.error(f"Error in get_monthly_reports: {e}", exc_info=True)
        return {}

@manager_required
async def total_report(update: Update, context: CallbackContext) -> None:
    """Show total reports for current and previous month"""
    try:
        now = datetime.now()
        current_month = now.month
        current_year = now.year
        
        # Calculate previous month and year
        prev_month = current_month - 1 if current_month > 1 else 12
        prev_year = current_year if current_month > 1 else current_year - 1
        
        # Get reports for both months
        current_reports = await get_monthly_reports(current_month, current_year)
        prev_reports = await get_monthly_reports(prev_month, prev_year)
        
        # Get all unique employee names from both months
        all_employees = set(current_reports.keys()).union(set(prev_reports.keys()))
        
        if not all_employees:
            await update.message.reply_text("No reports found for the current or previous month.")
            return
        
        # Prepare the response
        response = [
            "📊 *Monthly Report Statistics*\n",
            f"*Current Month ({current_month}/{current_year}):*\n"
        ]
        
        # Add current month data
        if current_reports:
            current_month_data = []
            for emp in sorted(all_employees):
                count = current_reports.get(emp, 0)
                current_month_data.append(f"• {emp}: {count} report{'s' if count != 1 else ''}")
            response.append("\n".join(current_month_data))
        else:
            response.append("No reports for current month.")
        
        # Add previous month data
        response.append(f"\n*Previous Month ({prev_month}/{prev_year}):*\n")
        if prev_reports:
            prev_month_data = []
            for emp in sorted(all_employees):
                count = prev_reports.get(emp, 0)
                prev_month_data.append(f"• {emp}: {count} report{'s' if count != 1 else ''}")
            response.append("\n".join(prev_month_data))
        else:
            response.append("No reports for previous month.")
        
        # Send the response
        await update.message.reply_text("\n".join(response), parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in total_report: {e}", exc_info=True)
        await update.message.reply_text("An error occurred while generating the report. Please try again later.")

@manager_required
async def download_excel(update: Update, context: CallbackContext) -> None:
    """Send the Excel report file to the user"""
    try:
        # Get the Excel file path
        excel_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                'Analytics', 'Daily_reports.xlsx')
        
        # Check if file exists
        if not os.path.exists(excel_file):
            await update.message.reply_text("❌ No report file found. Please submit some reports first.")
            return
        
        # Send the file
        with open(excel_file, 'rb') as file:
            await update.message.reply_document(
                document=file,
                filename=f"daily_reports_{datetime.now().strftime('%Y%m%d')}.xlsx",
                caption="📊 Here's the latest report file."
            )
            
    except Exception as e:
        logger.error(f"Error in download_excel: {e}", exc_info=True)
        await update.message.reply_text("❌ An error occurred while preparing the report file. Please try again later.")

async def help_command(update: Update, context: CallbackContext) -> None:
    """Send help message"""
    try:
        # Get language strings
        lang = context.user_data.get('language', 'en')
        strings = get_strings(lang)
        
        # Get user ID for permission check
        user = update.effective_user
        is_manager = str(user.id) == MANAGER_ID
        
        # Build help text with proper escaping for markdown
        help_text = [
            "*🤖 Daily Report Bot Help*\n",
            "*Available commands:*\n"
        ]
        
        # Regular user commands
        help_text.extend([
            "• /start - Start a new report",
            "• /help - Show this help message",
            "• /whoreported - Check who has reported today",
            "• /leader - Submit a leader report",
            "• /cancel - Cancel current operation"
        ])
        
        # Manager-only commands
        if is_manager:
            help_text.extend([
                "\n*Manager Commands:*\n",
                "• /total_report - Show monthly report statistics",
                "• /excel - Download the latest report as Excel file",
                "• /rating - Submit a rating"
            ])
        
        help_text = "\n".join(help_text)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=help_text,
            parse_mode='MarkdownV2',
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Error in help_command: {e}", exc_info=True)
        # Fallback to simple text without markdown
        fallback_text = (
            "🤖 *Daily Report Bot Help*\n\n"
            "Available commands:\n"
            "/start - Start a new report\n"
            "/help - Show this help message\n"
            "/whoreported - Check who has reported today\n"
            "/total_report - Show monthly report statistics\n"
            "/excel - Download the latest report as Excel file\n"
            "/leader - Submit a leader report\n"
            "/rating - Submit a rating\n"
            "/cancel - Cancel current operation"
        )
        await update.message.reply_text(fallback_text)


async def handle_manager_approval(update: Update, context: CallbackContext) -> int:
    """Handle report approval by manager"""
    # Get language strings
    lang = context.user_data.get('language', 'en')
    strings = get_strings(lang)
    
    query = update.callback_query
    await query.answer()
    
    # Extract report_id from callback data
    report_id = query.data.split('_')[1]
    
    # Store report_id in context.user_data
    context.user_data['report_id'] = report_id
    
    # Create rating keyboard
    keyboard = [
        [InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(1, 6)],
        [InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(6, 11)],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Edit the original message to show rating buttons
    try:
        # Store the original message ID for later use
        context.user_data['original_report_message_id'] = query.message.message_id
        
        # Edit the original message to show rating buttons
        await query.edit_message_text(
            text=query.message.text + "\n\nPlease rate the employee's performance from 1 to 10:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        # Fallback: send a new message if editing fails
        message = await query.message.reply_text(
            text="Please rate the employee's performance from 1 to 10:",
            reply_markup=reply_markup
        )
        context.user_data['rating_message_id'] = message.message_id
    
    return MANAGER_RATING

async def handle_manager_rating(update: Update, context: CallbackContext) -> int:
    """Handle manager rating"""
    # Get language strings
    lang = context.user_data.get('language', 'en')
    strings = get_strings(lang)
    
    query = update.callback_query
    await query.answer()
    
    # Save rating
    rating = int(query.data.split('_')[1])
    context.user_data['manager_rating'] = rating
    
    # Create comment decision keyboard
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes", callback_data="comment_yes"),
            InlineKeyboardButton("❌ No", callback_data="comment_no")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        # Get the original message text without the rating prompt
        original_text = "\n".join(query.message.text.split("\n")[:-1])  # Remove last line (rating prompt)
        
        # Update the original message with the rating and comment decision
        await query.edit_message_text(
            text=f"{original_text}\n\n✅ Rating {rating} has been recorded. Would you like to add a comment?",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        # Fallback: send a new message if editing fails
        message = await query.message.reply_text(
            text=f"✅ Rating {rating} has been recorded. Would you like to add a comment?",
            reply_markup=reply_markup
        )
        context.user_data['comment_message_id'] = message.message_id
    
    return MANAGER_COMMENT

async def handle_comment_decision(update: Update, context: CallbackContext) -> int:
    """Handle manager's decision about adding a comment"""
    # Get language strings
    lang = context.user_data.get('language', 'en')
    strings = get_strings(lang)
    
    query = update.callback_query
    await query.answer()
    
    decision = query.data.split('_')[1]
    
    if decision == 'yes':
        try:
            # Get the original message text without the last line
            original_text = "\n".join(query.message.text.split("\n")[:-1])
            
            # Update the original message to prompt for comment
            await query.edit_message_text(
                text=f"{original_text}\n\n📝 Please enter your comments:",
                reply_markup=None,  # Remove the buttons
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Store the message ID for the comment prompt
            context.user_data['comment_prompt_id'] = query.message.message_id
            return MANAGER_COMMENT
            
        except Exception as e:
            logger.error(f"Error editing message for comment: {e}")
            # Fallback: send a new message if editing fails
            message = await query.message.reply_text("📝 Please enter your comments:")
            context.user_data['comment_prompt_id'] = message.message_id
            return MANAGER_COMMENT
    else:
        # If no comment, save feedback and delete the original message
        try:
            # Delete the original report message
            if 'original_report_message_id' in context.user_data:
                try:
                    await context.bot.delete_message(
                        chat_id=query.message.chat_id,
                        message_id=context.user_data['original_report_message_id']
                    )
                except Exception as e:
                    logger.error(f"Error deleting original report message: {e}")
            
            # Save feedback without comment
            await save_manager_feedback(update, context, "")
            
            # Clean up
            if 'original_report_message_id' in context.user_data:
                del context.user_data['original_report_message_id']
                
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error in comment decision handling: {e}")
            await query.message.reply_text("❌ An error occurred while processing your request.")
            return ConversationHandler.END

async def handle_manager_comment(update: Update, context: CallbackContext) -> int:
    """Handle receiving manager's comment"""
    # Get language strings
    lang = context.user_data.get('language', 'en')
    strings = get_strings(lang)
    
    comment = update.message.text
    
    try:
        # Delete the original report message if it exists
        if 'original_report_message_id' in context.user_data:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=context.user_data['original_report_message_id']
                )
            except Exception as e:
                logger.error(f"Error deleting original report message: {e}")
        
        # Save the feedback with the comment
        await save_manager_feedback(update, context, comment)
        
        # Clean up user data
        if 'original_report_message_id' in context.user_data:
            del context.user_data['original_report_message_id']
        
        # Delete the comment prompt message if it exists
        if 'comment_prompt_id' in context.user_data:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=context.user_data['comment_prompt_id']
                )
            except Exception as e:
                logger.error(f"Error deleting comment prompt message: {e}")
            finally:
                del context.user_data['comment_prompt_id']
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in handle_manager_comment: {e}")
        await update.message.reply_text("❌ An error occurred while saving your comment. Please try again.")
        return ConversationHandler.END

async def save_manager_feedback(update: Update, context: CallbackContext, comment: str) -> None:
    """Save manager feedback"""
    # Get language strings
    lang = context.user_data.get('language', 'en')
    strings = get_strings(lang)
    
    try:
        report_id = context.user_data.get('report_id')
        manager_rating = context.user_data.get('manager_rating', 0)
        
        if not report_id:
            logger.error("Report ID not found in context")
            return
            
        # Path to main JSON file - using relative path to the Analytics folder in the parent directory
        analytics_dir = Path(__file__).parent.parent / 'Analytics'
        analytics_dir.mkdir(parents=True, exist_ok=True)
        json_file = analytics_dir / 'Daily_reports.json'
        
        if not json_file.exists():
            logger.error("Reports file not found")
            return
            
        with open(json_file, 'r', encoding='utf-8') as f:
            reports = json.load(f)
            
        # Find and update the report
        for report in reports:
            if report.get('id') == report_id:
                report['status'] = 'approved'
                report['manager_rating'] = manager_rating
                report['manager_comment'] = comment
                report['manager_feedback'] = {
                    'rating': manager_rating,
                    'comment': comment,
                    'timestamp': datetime.now().isoformat(),
                    'manager_id': update.effective_user.id
                }
                
                # Get the complete report data, preserving all original information
                report_data = report.get('data', {})
                
                # Ensure we have all the original data
                if not report_data:
                    report_data = report.copy()
                    # Remove non-data fields
                    for field in ['id', 'timestamp', 'status', 'manager_feedback', 'created_at', 'updated_at']:
                        report_data.pop(field, None)
                
                # Ensure problems data is properly included
                if 'problems' in report and 'problems' not in report_data:
                    report_data['problems'] = report['problems']
                
                # Ensure live_events data is properly included
                if 'live_events' in report and 'live_events' not in report_data:
                    report_data['live_events'] = report['live_events']
                
                # Ensure each problem has its live event data
                if 'problems' in report_data and 'live_events' in report_data:
                    for i, problem in enumerate(report_data['problems']):
                        # Ensure category and subcategory are included
                        if 'category' not in problem and 'type' in problem:
                            problem['category'] = problem['type']
                        if 'subcategory' not in problem and 'subtype' in problem:
                            problem['subcategory'] = problem['subtype']
                        
                        # Handle live events
                        if problem.get('type') in ['Live Event', 'Live events']:
                            # First try to get from the problem itself (new format)
                            if 'live_event_name' not in problem or 'live_event_source' not in problem:
                                # Fall back to live_events dictionary (old format)
                                live_event = report_data.get('live_events', {}).get(str(i), {})
                                if live_event:
                                    problem['live_event_name'] = live_event.get('name', 'Unspecified')
                                    problem['live_event_source'] = live_event.get('source', 'Unspecified')
                
                # Add manager feedback to report data
                report_data['manager_rating'] = manager_rating
                report_data['manager_comment'] = comment
                
                # Update the report dictionary with the complete data
                report['data'] = report_data
                
                # Save to Excel with the complete data
                excel_file = save_to_excel(report_data)
                
                # Save the updated report back to the main reports.json
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(reports, f, ensure_ascii=False, indent=2, default=str)
                
                # Generate the formatted report using format_report with escape_text=False to prevent double escaping
                formatted_report = format_report(report_data, escape_text=False)
                
                # Prepare the final report with manager's feedback
                report_text = (
                    "📋 *Final Approved Report*\n\n"
                    f"👤 *Employee:* {report_data.get('employee', 'Unspecified')}\n"
                    f"🕒 *Submission Time:* {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"⭐ *Employee Performance Rating:* {report_data.get('rating', 'Not rated')}\n"
                    f"😊 *Mood:* {report_data.get('mood', 'Not specified')}\n"
                    f"🏆 *Manager's Rating:* {manager_rating}/10\n"
                )
                
                # Add work sections if they exist
                work_sections = report_data.get('work_sections', [])
                if work_sections:
                    sections_text = ', '.join(work_sections)
                    report_text += f"📋 *Work Sections:* {sections_text}\n\n"
                
                # Add problems from the formatted report if they exist
                if '⚠️ *Reported Issues:*' in formatted_report:
                    problems_section = formatted_report.split('⚠️ *Reported Issues:*', 1)[1]
                    # Only include the problems section if it's not already in the report
                    if '⚠️ *Reported Issues:*' not in report_text:
                        report_text += "\n⚠️ *Reported Issues:*" + problems_section
                
                # Add manager's comment with better formatting
                if comment:
                    report_text += "\n📝 *Manager's Comments:*\n"
                    # Split comment into lines and add bullet points
                    comment_lines = [line.strip() for line in comment.split('\n') if line.strip()]
                    for line in comment_lines:
                        report_text += f"• {line}\n"
                
                # Send final report to Telegram group
                try:
                    logger.info("Sending report to @ihtv_report_group...")
                    await context.bot.send_message(
                        chat_id='@ihtv_report_group',
                        text=report_text,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    logger.info("Successfully sent report to @ihtv_report_group")
                    
                    # Send confirmation to manager
                    try:
                        if update.callback_query and update.callback_query.message:
                            chat_id = update.callback_query.message.chat_id
                            message_id = update.callback_query.message.message_id
                            await update.callback_query.answer()
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text="✅ گزارش با موفقیت ثبت و در گروه ارسال شد.",
                                reply_to_message_id=message_id
                            )
                        elif update.message:
                            await update.message.reply_text("✅ گزارش با موفقیت ثبت و در گروه ارسال شد.")
                    except Exception as confirm_error:
                        logger.error(f"Error sending confirmation to manager: {confirm_error}", exc_info=True)
                        
                except Exception as group_error:
                    logger.error(f"Error sending report to @ihtv_report_group: {group_error}", exc_info=True)
                    
                    # Notify manager about the error
                    try:
                        error_msg = "❌ خطا در ارسال گزارش به گروه. لطفاً دوباره تلاش کنید."
                        if update.callback_query and update.callback_query.message:
                            await update.callback_query.answer()
                            await context.bot.send_message(
                                chat_id=update.callback_query.message.chat_id,
                                text=error_msg,
                                reply_to_message_id=update.callback_query.message.message_id
                            )
                        elif update.message:
                            await update.message.reply_text(error_msg)
                    except Exception as error_error:
                        logger.error(f"Error while notifying about error: {error_error}", exc_info=True)
                
                break
                
        # Save changes
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(reports, f, ensure_ascii=False, indent=2)
        
        # If confirmation message hasn't been sent yet, send it
        try:
            success_message = "✅ Feedback submitted successfully."
            if update.callback_query and update.callback_query.message and not update.callback_query.message.text.startswith(success_message):
                await update.callback_query.edit_message_text(success_message)
            elif update.message and not (hasattr(update, 'already_replied') and update.already_replied):
                await update.message.reply_text(success_message)
                update.already_replied = True
        except Exception as msg_error:
            logger.error(f"Error sending confirmation message: {msg_error}", exc_info=True)
            
    except Exception as e:
        logger.error(f"Error saving manager feedback: {e}", exc_info=True)
        try:
            error_message = "❌ An error occurred while saving your feedback."
            if update.callback_query and update.callback_query.message:
                await update.callback_query.edit_message_text(error_message)
            elif update.message:
                await update.message.reply_text(error_message)
            else:
                logger.error("Could not send error message: No message or callback_query available")
        except Exception as msg_error:
            logger.error(f"Error sending error message: {msg_error}", exc_info=True)

async def rating_menu(update: Update, context: CallbackContext) -> int:
    """Handle the Rating menu option with enhanced UI"""
    user = update.effective_user
    if str(user.id) != MANAGER_ID:
        if update.message:
            await update.message.reply_text(
                "🔒 *Access Denied*\n\n"
                "You're not authorized to access the Manager Self-Rating system.",
                parse_mode=ParseMode.MARKDOWN
            )
        return ConversationHandler.END
    
    keyboard = [
        [InlineKeyboardButton("🌟 Start Self-Rating", callback_data="start_rating")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_message = (
        "🌟 *Manager Self-Rating System* 🌟\n\n"
        "Welcome to the Manager Self-Rating tool. This tool helps you reflect on your day and provide valuable feedback.\n\n"
        "The process will take less than a minute and includes:\n"
        "• Rating your daily performance\n"
        "• Sharing your current mood\n"
        "• Adding optional comments\n\n"
        "Your feedback is important for continuous improvement!"
    )
    
    await update.message.reply_text(
        welcome_message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    return RATING_MENU

async def handle_rating_score(update: Update, context: CallbackContext) -> int:
    """Handle rating score selection with enhanced UI"""
    query = update.callback_query
    await query.answer()
    
    # Create number buttons 1-10 with emojis
    keyboard = []
    score_emojis = ["😢", "😞", "😐", "🙂", "😊", "😃", "😁", "🤩", "🤯", "🏆"]
    for i in range(1, 11):
        emoji = score_emojis[i-1] if i <= len(score_emojis) else "⭐"
        keyboard.append(InlineKeyboardButton(f"{emoji} {i}", callback_data=f"score_{i}"))
    
    # Split into two rows of 5 buttons each
    reply_markup = InlineKeyboardMarkup([keyboard[:5], keyboard[5:]])
    
    rating_prompt = (
        "📊 *Daily Performance Rating*\n\n"
        "On a scale of 1-10, how would you rate your performance today?\n\n"
        "1 = Very Poor | 5 = Average | 10 = Outstanding\n\n"
        "Select your rating:"
    )
    
    await query.edit_message_text(
        rating_prompt,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    return RATING_SCORE

async def handle_rating_mood(update: Update, context: CallbackContext) -> int:
    """Handle mood selection with enhanced UI"""
    query = update.callback_query
    await query.answer()
    
    # Store the score
    score = int(query.data.split('_')[1])
    context.user_data['rating_score'] = score
    
    # Create mood buttons with more options and emojis
    mood_options = [
        ("😊 Happy", "I'm feeling great and productive today!"),
        ("😌 Content", "I'm satisfied with how things went."),
        ("😐 Neutral", "It was a regular day, nothing special."),
        ("😕 Stressed", "Feeling a bit overwhelmed today."),
        ("😔 Down", "Not my best day, to be honest.")
    ]
    
    keyboard = []
    for mood, _ in mood_options:
        mood_key = mood.lower().split()[0]  # Get first word as key
        keyboard.append([InlineKeyboardButton(mood, callback_data=f"mood_{mood_key}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    mood_prompt = (
        "🌤️ *How are you feeling today?*\n\n"
        "Your mood helps us understand your day better. Select the option that best describes how you're feeling right now.\n\n"
        "This information is completely confidential and will only be used for internal improvement purposes."
    )
    
    await query.edit_message_text(
        mood_prompt,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    return RATING_MOOD

async def handle_rating_comment(update: Update, context: CallbackContext) -> int:
    """Handle optional comments with enhanced UI"""
    query = update.callback_query
    await query.answer()
    
    # Store the mood
    mood = query.data.split('_')[1]
    context.user_data['rating_mood'] = mood
    
    # Create a nice looking keyboard with a skip button
    keyboard = [
        [InlineKeyboardButton("⏭️ Skip Comment", callback_data="skip_comment")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    comment_prompt = (
        "📝 *Additional Comments*\n\n"
        "Would you like to add any comments about your day? This is optional but valuable feedback.\n\n"
        "You can share:\n"
        "• What went well today\n"
        "• Any challenges you faced\n"
        "• Suggestions for improvement\n\n"
        "Or simply tap 'Skip Comment' below if you have nothing to add."
    )
    
    # Store the message ID so we can edit it later
    message = await query.edit_message_text(
        comment_prompt,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Store the message ID in user_data for later cleanup
    if hasattr(message, 'message_id'):
        context.user_data['last_message_id'] = message.message_id
    return RATING_COMMENT

async def save_rating(update: Update, context: CallbackContext) -> int:
    """Save the rating and show confirmation"""
    user_data = context.user_data
    
    # Get the comment
    if update.callback_query and update.callback_query.data == "skip_comment":
        comment = "No additional comments provided."
        await update.callback_query.answer()
        # Delete the message that asked for comments
        try:
            await update.callback_query.delete_message()
        except Exception as e:
            try:
                # If delete fails, try to edit the message instead
                await update.callback_query.edit_message_text(
                    text="Processing your feedback..."
                )
            except Exception as edit_error:
                logger.error(f"Error cleaning up skip message: {edit_error}")
    else:
        # If it's a message (not a callback), get the text
        if update.message:
            comment = update.message.text
            # Delete the previous message that asked for comments
            if 'last_message_id' in user_data:
                try:
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=user_data['last_message_id']
                    )
                except Exception as e:
                    try:
                        # If delete fails, try to edit the message instead
                        await context.bot.edit_message_text(
                            chat_id=update.effective_chat.id,
                            message_id=user_data['last_message_id'],
                            text="Processing your feedback..."
                        )
                    except Exception as edit_error:
                        logger.error(f"Error cleaning up message: {edit_error}")
        else:
            comment = "No comments provided."
    
    # Store the comment in user_data
    user_data['rating_comment'] = comment
    
    # Get current date and time
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    
    # Prepare the rating data
    rating_data = {
        'date': date_str,
        'time': time_str,
        'score': user_data['rating_score'],
        'mood': user_data['rating_mood'],
        'comment': comment
    }
    
    # Use the same Analytics folder as excel_handler.py
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    analytics_dir = Path(base_dir) / 'Analytics'
    analytics_dir.mkdir(exist_ok=True)
    
    # Save to JSON file
    try:
        json_path = analytics_dir / 'manager.json'
        if json_path.exists():
            with open(json_path, 'r', encoding='utf-8') as f:
                ratings = json.load(f)
        else:
            ratings = []
        
        ratings.append(rating_data)
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(ratings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving to JSON: {e}")
    
    # Save to Excel
    try:
        import pandas as pd
        excel_path = analytics_dir / 'manager.xlsx'
        if excel_path.exists():
            df = pd.read_excel(excel_path)
        else:
            df = pd.DataFrame(columns=['Date', 'Time', 'Score', 'Mood', 'Comment'])
        
        new_row = pd.DataFrame([{
            'Date': date_str,
            'Time': time_str,
            'Score': user_data['rating_score'],
            'Mood': user_data['rating_mood'],
            'Comment': comment
        }])
        
        df = pd.concat([df, new_row], ignore_index=True)
        df.to_excel(excel_path, index=False)
    except Exception as e:
        logger.error(f"Error saving to Excel: {e}")
    
    # Prepare the report message with better formatting
    mood_emojis = {
        'happy': '😊 Happy',
        'content': '😌 Content',
        'neutral': '😐 Neutral',
        'stressed': '😕 Stressed',
        'down': '😔 Down',
        'normal': '😐 Normal',
        'sad': '😔 Sad'
    }
    
    mood_display = mood_emojis.get(user_data['rating_mood'].lower(), user_data['rating_mood'].capitalize())
    
    # Get the comment from user_data to ensure we have the latest
    comment_text = user_data.get('rating_comment', 'No additional comments provided.')
    
    report_message = (
        "✨ *Manager Self-Assessment Report* ✨\n\n"
        "📅 *Date:* {date}\n"
        "⏰ *Time:* {time}\n"
        "\n📊 *Performance Summary*\n"
        "⭐ *Rating:* {score}/10\n"
        "😊 *Mood:* {mood}\n"
        "\n💬 *Comments*\n{comment}\n\n"
        "_This report has been recorded in the system._"
    ).format(
        date=date_str,
        time=time_str,
        score=user_data['rating_score'],
        mood=mood_display,
        comment=comment_text
    )
    
    # Send to the group
    try:
        await context.bot.send_message(
            chat_id='@ihtv_report_group',
            text=report_message,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error sending to group: {e}")
    
    # Prepare success message with a nice visual
    success_message = (
        "✅ *Rating Submitted Successfully!*\n\n"
        "Thank you for taking the time to complete your self-assessment. Your feedback is valuable!\n\n"
        "🌟 *Quick Stats*\n"
        f"• Your Rating: {user_data['rating_score']}/10\n"
        f"• Mood: {mood_display}\n"
        f"• Comments: {comment_text if len(comment_text) < 50 else comment_text[:50] + '...'}\n\n"
        "_You can submit another rating anytime using the /rating command._"
    )
    
    # Send confirmation to the user
    try:
        if update.callback_query and update.callback_query.data == "skip_comment":
            # If we came from a callback (skip comment button)
            await update.callback_query.edit_message_text(
                success_message,
                reply_markup=None,
                parse_mode=ParseMode.MARKDOWN
            )
        elif update.message:
            # If we came from a message (user typed a comment)
            await update.message.reply_text(
                success_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=ReplyKeyboardRemove()
            )
    except Exception as e:
        logger.error(f"Error sending success message: {e}")
        try:
            # Fallback if the above fails
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=success_message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as fallback_error:
            logger.error(f"Fallback error: {fallback_error}")
    
    return ConversationHandler.END

async def error_handler(update: Update, context: CallbackContext) -> None:
    """Bot error handler
    
    This function manages errors that occur in the bot and displays an appropriate message to the user.
    
    Args:
        update: Update object containing update information
        context: Callback context for conversation management
    """
    try:
        # Get the error details
        error = context.error
        error_type = type(error).__name__ if error else 'UnknownError'
        error_msg = str(error) if error else 'No error message'
        
        # Log the error with stack trace
        logger.error(f"Error type: {error_type}")
        logger.error(f"Error message: {error_msg}")
        logger.error(f"Update: {update}")
        logger.error("Traceback:", exc_info=error)
        
        # Log current conversation state and user data
        if hasattr(update, 'effective_chat') and update.effective_chat:
            logger.info(f"Chat ID: {update.effective_chat.id}")
        
        if hasattr(context, 'user_data') and context.user_data:
            logger.info(f"Current state: {context.user_data.get('_conversation_state', 'Not set')}")
            # Log user data but be careful with sensitive information
            user_data_copy = context.user_data.copy()
            # Remove any large or sensitive data before logging
            if 'documents' in user_data_copy:
                user_data_copy['documents'] = f"[List of {len(user_data_copy['documents'])} documents]"
            logger.info(f"User data: {json.dumps(user_data_copy, default=str, ensure_ascii=False, indent=2)}")
        
        # Prepare user-friendly error message
        error_message = '⚠️ An error occurred. Please try again.'
        
        # Special handling for specific error types
        if isinstance(error, AttributeError):
            error_message = '⚠️ A system error occurred. Please try again.'
        elif isinstance(error, TimeoutError):
            error_message = '⏱️ Operation timed out. Please try again.'
        elif isinstance(error, ValueError):
            error_message = '⚠️ Invalid input. Please try again.'
        
        # Try to send the error message to the user
        try:
            # Handle callback queries (inline keyboard buttons)
            if update and update.callback_query:
                try:
                    # First try to answer the callback to prevent "loading" animation
                    try:
                        await update.callback_query.answer()
                    except Exception as e:
                        logger.warning(f"Error answering callback: {e}")
                    
                    # Then try to edit the message
                    try:
                        await update.callback_query.edit_message_text(
                            text=error_message,
                            reply_markup=InlineKeyboardMarkup([[]])  # Empty inline keyboard
                        )
                        return  # Successfully handled
                    except Exception as edit_error:
                        logger.warning(f"Failed to edit message: {edit_error}")
                        # If editing fails, try to send a new message
                        await update.callback_query.message.reply_text(
                            error_message,
                            reply_markup=ReplyKeyboardRemove()
                        )
                except Exception as callback_error:
                    logger.error(f"Error handling callback query: {callback_error}")
            
            # Handle regular messages
            elif update and update.message:
                await update.message.reply_text(
                    error_message,
                    reply_markup=ReplyKeyboardRemove()
                )
            
            # Fallback if we can't determine the message type
            elif context.bot and update and update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=error_message,
                    reply_markup=ReplyKeyboardRemove()
                )
            else:
                logger.error("Could not determine how to send error message: No valid message target found")
                
        except Exception as send_error:
            logger.critical(f"Failed to send error message to user: {send_error}")
            
    except Exception as e:
        # If something goes wrong in the error handler itself
        logger.critical(f"CRITICAL ERROR in error handler: {e}", exc_info=True)
        
        # Try one last time to notify the user
        try:
            if update and update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text='⚠️ A critical error occurred. Please try again or contact support.',
                    reply_markup=ReplyKeyboardRemove()
                )
        except Exception as final_error:
            logger.critical(f"Failed to send critical error message: {final_error}")

async def leader_menu(update: Update, context: CallbackContext) -> int:
    """Handle the Leader menu option"""
    try:
        # Create rating buttons 1-10
        keyboard = []
        for i in range(1, 11):
            keyboard.append(InlineKeyboardButton(str(i), callback_data=f"leader_score_{i}"))
        
        # Split into two rows of 5 buttons each
        reply_markup = InlineKeyboardMarkup([keyboard[:5], keyboard[5:]])
        
        leader_prompt = (
            "👑 *Leadership Self-Assessment*\n\n"
            "On a scale of 1-10, how would you rate your leadership today?\n\n"
            "1 = Needs Improvement | 5 = Average | 10 = Outstanding"
        )
        
        if update.message:
            message = await update.message.reply_text(
                leader_prompt,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            message = await update.callback_query.edit_message_text(
                leader_prompt,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        
        # Store message ID for later cleanup
        if hasattr(message, 'message_id'):
            context.user_data['last_message_id'] = message.message_id
            
        return LEADER_RATING
    except Exception as e:
        logger.error(f"Error in leader_menu: {e}")
        if update.message:
            await update.message.reply_text("An error occurred. Please try again.")
        return ConversationHandler.END

async def handle_leader_rating(update: Update, context: CallbackContext) -> int:
    """Handle leader rating selection"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Store the rating
        rating = int(query.data.split('_')[-1])
        context.user_data['leader_rating'] = rating
        
        # Initialize selected staff in user_data if not exists
        if 'selected_staff' not in context.user_data:
            context.user_data['selected_staff'] = set()
        
        # Create staff selection keyboard with checkboxes
        keyboard = []
        temp_row = []
        
        # Add staff buttons with checkboxes for selection
        for i, emp in enumerate(EMPLOYEES):
            staff_name = emp['simple_display']
            # Check if this staff is already selected
            is_selected = i in context.user_data['selected_staff']
            emoji = "✅ " if is_selected else "◻️ "
            temp_row.append(InlineKeyboardButton(
                f"{emoji}{staff_name}",
                callback_data=f"toggle_staff_{i}"
            ))
            
            # Add rows with 2 buttons each
            if len(temp_row) == 2:
                keyboard.append(temp_row)
                temp_row = []
        
        # Add any remaining buttons
        if temp_row:
            keyboard.append(temp_row)
        
        # Add action buttons
        keyboard.append([
            InlineKeyboardButton("✅ Done Selecting", callback_data="staff_done"),
            InlineKeyboardButton("🔁 Clear All", callback_data="staff_clear")
        ])
        keyboard.append([
            InlineKeyboardButton("⏭️ Skip This Step", callback_data="skip_staff")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        staff_prompt = (
            "👥 *Team Member Recognition*\n\n"
            "Would you like to recognize any team member for their work today?\n\n"
            "Select a team member to describe their contribution, or skip this step."
        )
        
        message = await query.edit_message_text(
            staff_prompt,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Store message ID for later cleanup
        if hasattr(message, 'message_id'):
            context.user_data['last_message_id'] = message.message_id
            
        return LEADER_STAFF
    except Exception as e:
        logger.error(f"Error in handle_leader_rating: {e}")
        await query.edit_message_text("An error occurred. Please try again.")
        return ConversationHandler.END

async def handle_leader_staff(update: Update, context: CallbackContext) -> int:
    """Handle staff member selection for recognition"""
    try:
        query = update.callback_query
        await query.answer()
        
        logger.debug(f"Callback data: {query.data}")
        
        # Initialize selected_staff if not exists
        if 'selected_staff' not in context.user_data:
            context.user_data['selected_staff'] = set()
        
        # Handle different callback actions
        if query.data == 'staff_done':
            if not context.user_data['selected_staff']:
                await query.answer("👥 Please select team members or skip", show_alert=True)
                return LEADER_STAFF
                
            # Store selected staff names
            selected_staff = []
            for idx in context.user_data['selected_staff']:
                if 0 <= idx < len(EMPLOYEES):
                    staff_data = EMPLOYEES[idx]
                    staff_name = staff_data['data'].get('name', 'Unknown')
                    selected_staff.append(staff_name)
            
            context.user_data['leader_staff'] = ", ".join(selected_staff)
            logger.info(f"Selected staff: {context.user_data['leader_staff']}")
            
            # Proceed to issue description
            return await proceed_to_issue_description(update, context)
            
        elif query.data == 'staff_clear':
            context.user_data['selected_staff'] = set()
            
        elif query.data.startswith('toggle_staff_'):
            try:
                staff_idx = int(query.data.split('_')[2])
                if staff_idx in context.user_data['selected_staff']:
                    context.user_data['selected_staff'].remove(staff_idx)
                else:
                    context.user_data['selected_staff'].add(staff_idx)
                    # Provide haptic feedback for selection
                    await query.answer("👤 Selected")
            except (IndexError, ValueError) as e:
                logger.error(f"Error toggling staff: {e}")
        
        # Update the staff selection keyboard
        return await update_staff_selection(update, context)
        
    except Exception as e:
        logger.error(f"Error in handle_leader_staff: {str(e)}", exc_info=True)
        try:
            await query.edit_message_text(
                "❌ Oops! Something went wrong.\nPlease try again or /cancel to start over.",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
        return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"Error in handle_leader_staff: {str(e)}", exc_info=True)
        try:
            if 'query' in locals():
                await query.edit_message_text("❌ An error occurred while processing your selection. Please try again.")
            else:
                logger.error("Query object not available to send error message")
        except Exception as err:
            logger.error(f"Could not send error message: {err}")
        return ConversationHandler.END

async def handle_leader_issue_description(update: Update, context: CallbackContext) -> int:
    """Handle the issue description for the selected staff member"""
    try:
        # Store the issue description
        context.user_data['staff_issue'] = update.message.text
        
        # Ask for optional comment
        comment_prompt = (
            "💬 *Optional Comment*\n\n"
            "Would you like to add any additional comments about today's leadership?\n\n"
            "You can share:\n"
            "• Key achievements\\n"
            "• Challenges faced\\n"
            "• Plans for tomorrow\n\n"
            "Or tap 'Skip' below if you have nothing to add."
        )
        
        keyboard = [
            [InlineKeyboardButton("⏭️ Skip Comment", callback_data="skip_comment")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Clean up the previous message if possible
        if 'last_message_id' in context.user_data:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=context.user_data['last_message_id']
                )
            except:
                pass
        
        message = await update.message.reply_text(
            comment_prompt,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Store message ID for later cleanup
        if hasattr(message, 'message_id'):
            context.user_data['last_message_id'] = message.message_id
            
        return LEADER_COMMENT
        
    except Exception as e:
        logger.error(f"Error in handle_leader_issue_description: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ An error occurred while processing your response. Please try again.")
        return ConversationHandler.END

async def update_staff_selection(update: Update, context: CallbackContext) -> int:
    """Update the staff selection keyboard"""
    try:
        query = update.callback_query
        
        # Create keyboard with staff members in two columns
        keyboard = []
        row = []
        
        for idx, employee in enumerate(EMPLOYEES):
            employee_name = employee['data'].get('name', 'Unknown')
            is_selected = idx in context.user_data.get('selected_staff', set())
            
            # Create button with emoji for selection state
            emoji = "🔘" if not is_selected else "✅"
            btn_text = f"{emoji} {employee_name}"
            
            row.append(
                InlineKeyboardButton(
                    btn_text,
                    callback_data=f"toggle_staff_{idx}"
                )
            )
            
            # Add new row every 2 buttons
            if len(row) >= 2:
                keyboard.append(row)
                row = []
        
        # Add any remaining buttons
        if row:
            keyboard.append(row)
        
        # Add action buttons
        action_row = []
        
        if context.user_data.get('selected_staff'):
            action_row.append(
                InlineKeyboardButton("🗑️ Clear All", callback_data="staff_clear")
            )
        
        action_row.extend([
            InlineKeyboardButton("⏭️ Skip", callback_data="skip_staff"),
            InlineKeyboardButton("✅ Done", callback_data="staff_done")
        ])
        
        keyboard.append(action_row)
        
        # Update the message
        selected_count = len(context.user_data.get('selected_staff', []))
        selection_text = (
            f"👥 *Select Team Members* {'(' + str(selected_count) + ' selected)' if selected_count > 0 else ''}\n\n"
            "Tap names to select/deselect. Tap ✅ when done."
        )
        
        try:
            await query.edit_message_text(
                text=selection_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error updating message: {e}")
            # If message wasn't modified (no changes), ignore the error
            if "message is not modified" not in str(e).lower():
                raise
        
        return LEADER_STAFF
        
    except Exception as e:
        logger.error(f"Error in update_staff_selection: {e}", exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Couldn't update selection. Please try again.",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
        return ConversationHandler.END

async def proceed_to_issue_description(update: Update, context: CallbackContext) -> int:
    """Proceed to ask for issue description after staff selection"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Prepare the issue prompt
        issue_prompt = (
            f"📝 *Report for {context.user_data['leader_staff']}*\n\n"
            "Please briefly describe the issue or concern.\n"
            "_Example: \"Team member was 30 mins late for shift, affecting morning workflow\"_"
        )
        
        try:
            # Send new message instead of editing to prevent message flickering
            await query.delete_message()
            message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=issue_prompt,
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Store message ID for later cleanup
            context.user_data['last_message_id'] = message.message_id
            return LEADER_ISSUE
            
        except Exception as msg_err:
            logger.error(f"Error sending message: {msg_err}")
            raise
            
    except Exception as e:
        logger.error(f"Error in proceed_to_issue_description: {e}", exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Couldn't proceed. Please try /leader again.",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
        return ConversationHandler.END

async def handle_leader_skip_staff(update: Update, context: CallbackContext) -> int:
    """Handle skipping staff recognition"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Clear any previous selections
        if 'selected_staff' in context.user_data:
            del context.user_data['selected_staff']
            
        # Set default values
        context.user_data['leader_staff'] = 'None'
        context.user_data['staff_issue'] = 'No specific issue reported'
        
        # Ask for optional comment
        comment_prompt = (
            "💬 *Optional Comment*\n\n"
            "Would you like to add any comments about today's leadership?\n\n"
            "You can share:\n"
            "• Key achievements\\n"
            "• Challenges faced\\n"
            "• Plans for tomorrow\n\n"
            "Or tap 'Skip' below if you have nothing to add."
        )
        
        keyboard = [
            [InlineKeyboardButton("⏭️ Skip Comment", callback_data="skip_comment")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = await query.edit_message_text(
            comment_prompt,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Store message ID for later cleanup
        if hasattr(message, 'message_id'):
            context.user_data['last_message_id'] = message.message_id
            
        return LEADER_COMMENT
    except Exception as e:
        logger.error(f"Error in handle_leader_skip_staff: {e}")
        await query.edit_message_text("An error occurred. Please try again.")
        return ConversationHandler.END

async def save_leader_report(update: Update, context: CallbackContext) -> int:
    """Save the leader report and show confirmation"""
    try:
        # Get the comment if provided
        if update.callback_query and update.callback_query.data == "skip_comment":
            comment = "No additional comments provided."
            await update.callback_query.answer()
            # Clean up the message
            try:
                await update.callback_query.delete_message()
            except:
                pass
        else:
            comment = update.message.text
            # Clean up the previous message if possible
            if 'last_message_id' in context.user_data:
                try:
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=context.user_data['last_message_id']
                    )
                except:
                    pass
        
        # Get current date and time
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        
        # Prepare the report data
        report_data = {
            'date': date_str,
            'time': time_str,
            'rating': context.user_data.get('leader_rating', 'N/A'),
            'staff': context.user_data.get('leader_staff', 'None'),
            'staff_issue': context.user_data.get('staff_issue', 'No issue reported'),
            'comment': comment,
            'user_id': update.effective_user.id,
            'username': update.effective_user.username or 'N/A'
        }
        
        # Save to JSON file
        analytics_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / 'Analytics'
        analytics_dir.mkdir(exist_ok=True)
        
        json_path = analytics_dir / 'leader_reports.json'
        try:
            if json_path.exists():
                with open(json_path, 'r', encoding='utf-8') as f:
                    reports = json.load(f)
            else:
                reports = []
            
            reports.append(report_data)
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(reports, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving leader report to JSON: {e}")
        
        # Prepare success message
        success_message = (
            "✅ *Leadership Report Submitted*\n\n"
            f"⭐ *Your Rating:* {report_data['rating']}/10\n"
            f"👥 *Team Member:* {report_data['staff']}\n"
            f"📝 *Issue Reported:*\n{report_data['staff_issue']}\n\n"
            f"💬 *Additional Comments:*\n{report_data['comment']}\n\n"
            "_Thank you for your leadership feedback! This information helps us improve._"
        )
        
        # Send confirmation to the user
        if update.callback_query:
            await update.callback_query.message.reply_text(
                success_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=ReplyKeyboardRemove()
            )
        else:
            await update.message.reply_text(
                success_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=ReplyKeyboardRemove()
            )
        
        # Send the report to the group
        try:
            group_chat_id = '@ihtv_report_group'  # The group where reports should be sent
            
            # Helper function to escape markdown special characters for Telegram
            def escape_markdown(text):
                if not isinstance(text, str):
                    text = str(text)
                # Escape markdown special characters
                special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
                for ch in special_chars:
                    text = text.replace(ch, f'\\{ch}')
                return text
            
            # Format the message for the group
            username = escape_markdown(report_data['username'])
            staff = escape_markdown(report_data['staff'])
            date = escape_markdown(report_data['date'])
            time = escape_markdown(report_data['time'])
            issue = escape_markdown(report_data['staff_issue'])
            comment = escape_markdown(report_data['comment'])
            
            # Build the message with proper escaping
            group_message = (
                "📊 *New Leadership Report*\n\n"
                f"⭐ *Rating:* {escape_markdown(report_data['rating'])}/10\n"
                f"👤 *Reporter:* @{username} \(ID: `{report_data['user_id']}`\)\n"
                f"👥 *Team Member:* {staff}\n"
                f"📅 *Date:* {date} at {time}\n\n"
                f"📝 *Issue Reported:*\n{issue}\n\n"
                f"💬 *Comments:*\n{comment}"
            )
            
            # Send the message to the group
            await context.bot.send_message(
                chat_id=group_chat_id,
                text=group_message,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            logger.info(f"Leader report sent to group {group_chat_id}")
            
        except Exception as e:
            logger.error(f"Error sending leader report to group: {e}")
            # Try to notify admin if group send fails
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"⚠️ Failed to send leader report to group. Error: {str(e)}"
                )
            except:
                pass
        
        # Clean up user data
        for key in ['leader_rating', 'leader_staff', 'staff_issue', 'last_message_id']:
            context.user_data.pop(key, None)
            
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in save_leader_report: {e}")
        if update.message:
            await update.message.reply_text("An error occurred while saving your report. Please try again.")
        return ConversationHandler.END

def main():
    """Start the bot."""
    try:
        # Create the Application and pass it your bot's token.
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Define bot commands
        commands = [
            ('start', 'Start a new report'),
            ('help', 'Show help information'),
            ('whoreported', 'Check who has reported today'),
            ('total_report', 'Show monthly report statistics'),
            ('excel', 'Download report as Excel'),
            ('leader', 'Submit a leader report'),
            ('rating', 'Submit a rating'),
            ('cancel', 'Cancel current operation')
        ]

        # Add manager conversation handler
        manager_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(handle_manager_approval, pattern='^approve_'),
            ],
            states={
                MANAGER_RATING: [
                    CallbackQueryHandler(handle_manager_rating, pattern='^rate_\\d+$')
                ],
                MANAGER_COMMENT: [
                    CallbackQueryHandler(handle_comment_decision, pattern='^comment_(yes|no)$'),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manager_comment)
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )

        # Add Rating conversation handler
        rating_conv_handler = ConversationHandler(
            entry_points=[CommandHandler('rating', rating_menu)],
            states={
                RATING_MENU: [
                    CallbackQueryHandler(handle_rating_score, pattern='^start_rating$')
                ],
                RATING_SCORE: [
                    CallbackQueryHandler(handle_rating_mood, pattern='^score_')
                ],
                RATING_MOOD: [
                    CallbackQueryHandler(handle_rating_comment, pattern='^mood_')
                ],
                RATING_COMMENT: [
                    CallbackQueryHandler(save_rating, pattern='^skip_comment$'),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_rating)
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            conversation_timeout=300  # 5 minutes
        )
        application.add_handler(rating_conv_handler)
        
        # Add Leader conversation handler
        leader_conv_handler = ConversationHandler(
            entry_points=[CommandHandler('leader', leader_menu)],
            states={
                LEADER_RATING: [
                    CallbackQueryHandler(handle_leader_rating, pattern=r'^leader_score_\d+$')
                ],
                LEADER_STAFF: [
                    CallbackQueryHandler(handle_leader_staff, pattern=r'^(toggle_staff_\d+|staff_done|staff_clear|skip_staff)$')
                ],
                LEADER_ISSUE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leader_issue_description)
                ],
                LEADER_COMMENT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_leader_report),
                    CallbackQueryHandler(save_leader_report, pattern='^skip_comment$')
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            conversation_timeout=300  # 5 minutes
        )
        application.add_handler(leader_conv_handler)
        
        # Add command handlers
        application.add_handler(CommandHandler('whoreported', check_reports))
        application.add_handler(CommandHandler('total_report', total_report))
        application.add_handler(CommandHandler('excel', download_excel))
        application.add_handler(CommandHandler('rating', rating_menu))
        application.add_handler(CommandHandler('leader', leader_menu))
        
        # Add main conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                # State: User is selecting an employee
                SELECTING_EMPLOYEE: [
                    CallbackQueryHandler(employee_selected, pattern=r'^emp_\d+$')
                ],
                # State: User is selecting work sections
                SELECTING_WORK_SECTIONS: [
                    CallbackQueryHandler(handle_work_sections, pattern=r'^(section_\d+|sections_done)$')
                ],
                # State: User is selecting servers (if applicable)
                SELECTING_SERVER: [
                    CallbackQueryHandler(server_selected, pattern=r'^(srv_\d+|servers_done)$')
                ],
                # State: Asking if user had any problems
                ASK_PROBLEM: [
                    CallbackQueryHandler(handle_problem_response, pattern=r'^problem_(yes|no)$')
                ],
                # State: User is rating their work
                RATING: [
                    CallbackQueryHandler(handle_rating, pattern=r'^rate_([1-9]|10)$')
                ],
                # State: User is selecting their mood
                MOOD: [
                    CallbackQueryHandler(handle_mood, pattern=r'^mood_(happy|neutral|sad)$')
                ],
                # State: User can provide additional info
                ADDITIONAL_INFO: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_additional_info),
                    CommandHandler('skip', skip_additional_info)
                ],
                # State: User is selecting problem category (if they reported a problem)
                PROBLEM_CATEGORY: [
                    CallbackQueryHandler(handle_problem_category, pattern=r'^cat_|back_to_categories$')
                ],
                # State: User is selecting problem subcategory
                PROBLEM_TYPE: [
                    CallbackQueryHandler(handle_problem_category, pattern=r'^cat_|back_to_categories|sub_\d+$')
                ],
                # State: User is providing problem description or live event details
                PROBLEM_DESCRIPTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_problem_description),
                    CallbackQueryHandler(handle_problem_category, pattern=r'^back_to_categories$')
                ],
                # State: User is providing live event name (for live event problems)
                LIVE_EVENT_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_live_event_name)
                ],
                # State: User is selecting live event source
                LIVE_EVENT_SOURCE: [
                    CallbackQueryHandler(handle_live_event_source, pattern=r'^src_\d+$'),
                    # Add a fallback for any other input
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_live_event_source_fallback)
                ],
                # State: User can upload documents or finish the report
                DOCUMENT_UPLOAD: [
                    MessageHandler(filters.Document.ALL, handle_document),
                    CommandHandler('finish', finish_report)
                ],
                # State: Ask if user has more problems to report
                ASK_MORE_PROBLEMS: [
                    CallbackQueryHandler(handle_more_problems, pattern=r'^more_problems_(yes|no)$')
                ],
                # State: Ask if user has more problems to report
                ASK_MORE_PROBLEMS: [
                    CallbackQueryHandler(handle_more_problems, pattern=r'^more_problems_(yes|no)$')
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            allow_reentry=True
        )
        
        # Add conversation handlers to the application
        application.add_handler(conv_handler)
        application.add_handler(manager_conv_handler)
        application.add_handler(leader_conv_handler)

        # Add command handlers
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CommandHandler('cancel', cancel))
        application.add_handler(CommandHandler('leader', leader_menu))
        application.add_handler(CommandHandler('rating', rating_menu))
        
        # Add message handler for the "New Report" button
        application.add_handler(MessageHandler(
            filters.TEXT & filters.Regex(r'^📝 ثبت گزارش جدید$'),
            lambda update, context: start(update, context)
        ))
        
        # Set bot commands menu
        application.add_error_handler(error_handler)
        
        # Set bot commands (this will be done in the post_init phase)
        async def post_init(application: Application) -> None:
            await application.bot.set_my_commands(commands)
        
        application.post_init = post_init
        
        # Run the bot
        logger.info("Starting bot polling...")
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
        
    except Exception as e:
        logger.critical(f"Fatal error in main: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    main()
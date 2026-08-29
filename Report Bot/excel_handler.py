import os
import pandas as pd
from datetime import datetime
from typing import Dict, Any, Optional
import logging

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# مسیر ذخیره‌سازی فایل‌های اکسل
# Use a relative path to the Analytics folder in the parent directory
EXCEL_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'Analytics')
os.makedirs(EXCEL_FOLDER, exist_ok=True)
# مسیر فایل اکسل
EXCEL_FILE = os.path.join(EXCEL_FOLDER, 'Daily_reports.xlsx')

def get_monthly_filename() -> str:
    """تولید نام فایل ماهانه"""
    return EXCEL_FILE  # Always use the same filename instead of monthly files

def save_to_excel(user_data: Dict[str, Any]) -> str:
    """
    ذخیره اطلاعات کاربر در فایل اکسل
    
    Args:
        user_data: دیکشنری حاوی اطلاعات کاربر
        
    Returns:
        مسیر فایل ذخیره شده
    """
    try:
        # تبدیل تاریخ به رشته
        report_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # استخراج اطلاعات پایه
        report_id = user_data.get('id', '')
        employee = user_data.get('employee', 'نامشخص')
        servers = user_data.get('servers', [])
        server = ', '.join(servers) if servers else user_data.get('server', 'نامشخص')
        
        # تعیین وضعیت مشکل
        problems = user_data.get('problems', [])
        has_problem = bool(problems)
        
        # اگر مشکلاتی وجود دارد، برای هر مشکل یک ردیف ایجاد می‌کنیم
        if has_problem:
            all_data = []
            for i, problem in enumerate(problems):
                problem_data = {
                    'شناسه گزارش': report_id,
                    'تاریخ و زمان': report_time,
                    'کارمند': employee,
                    'سرور': server,
                    'وضعیت': 'مشکل',
                    'دسته‌بندی': problem.get('category', problem.get('type', 'عمومی')),  # Add category field
                    'نوع مشکل': problem.get('type', 'نامشخص'),
                    'توضیحات مشکل': problem.get('description', ''),
                    'امتیاز عملکرد': user_data.get('rating', ''),
                    'حالت روحی': user_data.get('mood', ''),
                    'توضیحات اضافی': user_data.get('additional_info', ''),
                    'امتیاز مدیر': user_data.get('manager_rating', ''),
                    'نظر مدیر': user_data.get('manager_comment', '')
                }
                
                # اگر مشکل مربوط به پخش زنده است، اطلاعات اضافی را اضافه می‌کنیم
                problem_type = problem.get('type', '')
                if problem_type in ['پخش', 'پخش زنده', 'Live Event', 'Broadcast']:
                    # First try to get from direct fields in the problem
                    live_event_name = problem.get('live_event_name')
                    live_event_source = problem.get('live_event_source')
                    
                    # If not found, try to get from nested live_events dictionary
                    if not live_event_name or not live_event_source:
                        live_events = problem.get('live_events', {})
                        if isinstance(live_events, dict):
                            if not live_event_name and 'name' in live_events:
                                live_event_name = live_events['name']
                            if not live_event_source and 'source' in live_events:
                                live_event_source = live_events['source']
                    
                    # If still not found, try to get from user_data's live_events
                    if (not live_event_name or not live_event_source) and 'live_events' in user_data:
                        problem_events = user_data['live_events'].get(str(i), {})
                        if not live_event_name and 'name' in problem_events:
                            live_event_name = problem_events['name']
                        if not live_event_source and 'source' in problem_events:
                            live_event_source = problem_events['source']
                    
                    # Add to problem data if we found any information
                    problem_data.update({
                        'نام برنامه زنده': live_event_name or 'نامشخص',
                        'منبع مشکل': live_event_source or 'نامشخص'
                    })
                else:
                    problem_data.update({
                        'نام برنامه زنده': '-',
                        'منبع مشکل': '-'
                    })
                
                all_data.append(problem_data)
            
            # ایجاد دیتافریم از لیست دیکشنری‌ها
            df = pd.DataFrame(all_data)
            
            # اطمینان از وجود تمام ستون‌های مورد نیاز
            required_columns = [
                'شناسه گزارش', 'تاریخ و زمان', 'کارمند', 'سرور', 'وضعیت', 'دسته‌بندی', 'نوع مشکل', 'توضیحات مشکل',
                'امتیاز عملکرد', 'حالت روحی', 'توضیحات اضافی', 'نام برنامه زنده', 'منبع مشکل',
                'امتیاز مدیر', 'نظر مدیر'
            ]
            
            # اضافه کردن ستون‌های گم‌شده با مقادیر پیش‌فرض
            for col in required_columns:
                if col not in df.columns:
                    df[col] = ''
        else:
            # اگر مشکلی وجود ندارد، یک ردیف عادی ایجاد می‌کنیم
            data = {
                'شناسه گزارش': [report_id],
                'تاریخ و زمان': [report_time],
                'کارمند': [employee],
                'سرور': [server],
                'وضعیت': ['عادی'],
                'دسته‌بندی': [''],
                'امتیاز عملکرد': [user_data.get('rating', '')],
                'حالت روحی': [user_data.get('mood', '')],
                'توضیحات اضافی': [user_data.get('additional_info', '')],
                'نوع مشکل': [''],
                'توضیحات مشکل': [''],
                'نام برنامه زنده': [''],
                'منبع مشکل': [''],
                'امتیاز مدیر': [user_data.get('manager_rating', '')],
                'نظر مدیر': [user_data.get('manager_comment', '')]
            }
            df = pd.DataFrame(data)
        
        # Use the fixed Excel file path
        excel_file = EXCEL_FILE
        
        # Check if file exists and update or append to it
        if os.path.exists(excel_file):
            try:
                # Read existing file
                existing_df = pd.read_excel(excel_file, engine='openpyxl')
                
                # Make sure the ID column exists in the existing dataframe
                if 'شناسه گزارش' not in existing_df.columns:
                    existing_df.insert(0, 'شناسه گزارش', '')
                
                # Check if this report ID already has rows in the spreadsheet
                if report_id:
                    # Coerce columns to string comparison to be safe
                    existing_df['شناسه گزارش'] = existing_df['شناسه گزارش'].astype(str).str.strip()
                    report_id_str = str(report_id).strip()
                    
                    mask = existing_df['شناسه گزارش'] == report_id_str
                    if mask.any():
                        # Find the first index where this report ID resides
                        first_idx = existing_df[mask].index[0]
                        # Drop all rows associated with this report ID
                        existing_df = existing_df.drop(existing_df[mask].index).reset_index(drop=True)
                        
                        # Split and insert new records at the original index
                        df_top = existing_df.iloc[:first_idx]
                        df_bottom = existing_df.iloc[first_idx:]
                        df = pd.concat([df_top, df, df_bottom], ignore_index=True)
                    else:
                        df = pd.concat([existing_df, df], ignore_index=True)
                else:
                    df = pd.concat([existing_df, df], ignore_index=True)
            except Exception as e:
                logger.error(f"Error reading/updating existing Excel file: {e}")
                # If there's an error reading the existing file, continue with just the new data
        
        # Save to Excel file
        try:
            df.to_excel(excel_file, index=False, engine='openpyxl')
            logger.info(f"Report successfully saved to {excel_file}")
        except Exception as e:
            logger.error(f"Error saving to Excel file: {e}")
            raise
        
        return excel_file
        
    except Exception as e:
        logger.error(f"خطا در ذخیره‌سازی گزارش در اکسل: {e}")
        raise

def get_monthly_report(month: Optional[int] = None, year: Optional[int] = None) -> pd.DataFrame:
    """
    دریافت گزارش ماهانه
    
    Args:
        month: شماره ماه (1-12)
        year: سال (مثلاً 1403)
        
    Returns:
        دیتافریم حاوی گزارش ماهانه
    """
    try:
        now = datetime.now()
        month = month or now.month
        year = year or now.year
        
        filename = os.path.join(EXCEL_FOLDER, f'reports_{year}_{month:02d}.xlsx')
        
        if not os.path.exists(filename):
            return pd.DataFrame()  # برگرداندن دیتافریم خالی اگر فایلی وجود ندارد
        
        return pd.read_excel(filename, engine='openpyxl')
    
    except Exception as e:
        logger.error(f"خطا در دریافت گزارش ماهانه: {e}")
        return pd.DataFrame()

def generate_summary_report(month: Optional[int] = None, year: Optional[int] = None) -> Dict[str, Any]:
    """
    تولید خلاصه گزارش ماهانه
    
    Returns:
        دیکشنری حاوی آمار و اطلاعات خلاصه
    """
    try:
        df = get_monthly_report(month, year)
        
        if df.empty:
            return {
                'status': 'error',
                'message': 'داده‌ای برای نمایش وجود ندارد.'
            }
        
        # محاسبه آمار
        total_reports = len(df)
        problem_reports = len(df[df['وضعیت'] == 'مشکل'])
        normal_reports = total_reports - problem_reports
        
        # محاسبه میانگین امتیاز (فقط گزارش‌های عادی)
        avg_rating = None
        if 'امتیاز عملکرد' in df.columns:
            try:
                avg_rating = df[df['امتیاز عملکرد'].notna()]['امتیاز عملکرد'].astype(float).mean()
                avg_rating = round(avg_rating, 2)
            except:
                pass
        
        # تعداد گزارش‌ها به تفکیک نوع مشکل
        problem_types = {}
        if 'نوع مشکل' in df.columns:
            problem_types = df['نوع مشکل'].value_counts().to_dict()
        
        # وضعیت روحی (فقط گزارش‌های عادی)
        mood_distribution = {}
        if 'حالت روحی' in df.columns:
            mood_distribution = df[df['حالت روحی'].notna()]['حالت روحی'].value_counts().to_dict()
        
        return {
            'status': 'success',
            'total_reports': total_reports,
            'problem_reports': problem_reports,
            'normal_reports': normal_reports,
            'avg_rating': avg_rating,
            'problem_types': problem_types,
            'mood_distribution': mood_distribution,
            'data': df.to_dict('records')
        }
        
    except Exception as e:
        logger.error(f"خطا در تولید خلاصه گزارش: {e}")
        return {
            'status': 'error',
            'message': str(e)
        }

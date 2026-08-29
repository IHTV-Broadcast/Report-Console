# -*- coding: utf-8 -*-

# English strings (default)
EN = {
    'welcome': "👋 Welcome to the Daily Report Bot!",
    'select_employee': "Please select your name from the list below:",
    'select_work_sections': "In which sections did you work? (You can select multiple)",
    'confirm_sections': "✅ Confirm and Continue",
    'select_server': "Please select the server:",
    'any_problems': "Did you encounter any issues today?",
    'problem_yes': "Yes, I had issues",
    'problem_no': "No issues",
    'select_problem_type': "Please select the type of problem:",
    'describe_problem': "Please describe the problem:",
    'rate_performance': "Rate your performance today from 1 to 10:",
    'select_mood': "How are you feeling today?",
    'additional_comments': "Any additional comments? (Optional)",
    'skip': "Skip",
    'submit_report': "✅ Submit Report",
    'report_submitted': "✅ Report submitted successfully!",
    'cancel': "❌ Cancel",
    'back': "🔙 Back"
}

# Arabic strings
AR = {
    'welcome': "👋 مرحبًا بك في بوت التقرير اليومي!",
    'select_employee': "الرجاء اختيار اسمك من القائمة أدناه:",
    'select_work_sections': "في أي أقسام عملت؟ (يمكنك اختيار أكثر من قسم)",
    'confirm_sections': "✅ تأكيد والمتابعة",
    'select_server': "الرجاء اختيار الخادم:",
    'any_problems': "هل واجهت أي مشاكل اليوم؟",
    'problem_yes': "نعم، واجهت مشاكل",
    'problem_no': "لا توجد مشاكل",
    'select_problem_type': "الرجاء اختيار نوع المشكلة:",
    'describe_problem': "الرجاء وصف المشكلة:",
    'rate_performance': "قيم أداءك اليوم من 1 إلى 10:",
    'select_mood': "كيف تشعر اليوم؟",
    'additional_comments': "أي تعليقات إضافية؟ (اختياري)",
    'skip': "تخطي",
    'submit_report': "✅ إرسال التقرير",
    'report_submitted': "✅ تم إرسال التقرير بنجاح!",
    'cancel': "❌ إلغاء",
    'back': "🔙 رجوع"
}

# Persian strings (existing)
FA = {
    'welcome': '👋 به ربات گزارش‌دهی روزانه خوش آمدید!',
    'select_employee': 'لطفاً نام خود را از لیست زیر انتخاب کنید:',
    'select_work_sections': 'در کدام بخش‌ها فعالیت کرده‌اید؟ (می‌توانید چند مورد را انتخاب کنید)',
    'confirm_sections': '✅ تأیید و ادامه',
    'select_server': 'لطفاً سرور مورد نظر را انتخاب کنید:',
    'any_problems': 'آیا امروز با مشکلی مواجه شدید؟',
    'problem_yes': 'بله، مشکل داشتم',
    'problem_no': 'خیر، مشکلی نداشتم',
    'select_problem_type': 'لطفاً نوع مشکل را انتخاب کنید:',
    'describe_problem': 'لطفاً مشکل را شرح دهید:',
    'rate_performance': 'به عملکرد امروز خود از 1 تا 10 چه امتیازی می‌دهید؟',
    'select_mood': 'امروز چه حسی دارید؟',
    'additional_comments': 'توضیحات اضافی (اختیاری):',
    'skip': 'رد کردن',
    'submit_report': '✅ ثبت گزارش',
    'report_submitted': '✅ گزارش با موفقیت ثبت شد!',
    'cancel': '❌ انصراف',
    'back': '🔙 بازگشت'
}

def get_strings(lang='fa'):
    """Get strings for the specified language"""
    if lang == 'ar':
        return AR
    elif lang == 'en':
        return EN
    return FA  # Default to Farsi

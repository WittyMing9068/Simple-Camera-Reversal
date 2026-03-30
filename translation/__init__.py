import re
import ast
import bpy

from . import zh_HANS

# 翻译唯一标识，建议使用插件名称
TRANSLATION_DOMAIN = "simple_camera_match" 

# 只需注册中文翻译，英文是源码默认语言
langs = {
    "zh_CN": zh_HANS.data, 
    "zh_HANS": zh_HANS.data,
}

# 获取Blender支持的语言列表
def get_language_list() -> list:
    try:
        bpy.context.preferences.view.language = ""
    except TypeError as e:
        matches = re.findall(r"\(([^()]*)\)", e.args[-1])
        if matches:
            return ast.literal_eval(f"({matches[-1]})")
    except Exception:
        pass
    return []

# 翻译辅助类
class TranslationHelper():
    def __init__(self, data: dict, lang='zh_HANS'):
        self.name = TRANSLATION_DOMAIN
        self.translations_dict = dict()

        for src, src_trans in data.items():
            key = ("Operator", src)
            self.translations_dict.setdefault(lang, {})[key] = src_trans
            key = ("*", src)
            self.translations_dict.setdefault(lang, {})[key] = src_trans
            key = (self.name, src)
            self.translations_dict.setdefault(lang, {})[key] = src_trans

    def register(self):
        try:
            bpy.app.translations.register(self.name, self.translations_dict)
        except(ValueError):
            pass

    def unregister(self):
        try:
            bpy.app.translations.unregister(self.name)
        except(ValueError):
            pass

I18N = {}
    
def register():
    global I18N
    try:
        all_languages = get_language_list()
        if not all_languages:
            # 无法获取语言列表时，直接注册所有翻译
            for lang_code, data in langs.items():
                helper = TranslationHelper(data, lang=lang_code)
                helper.register()
                I18N[lang_code] = helper
        else:
            for lang_code, data in langs.items():
                if lang_code in all_languages:
                    helper = TranslationHelper(data, lang=lang_code)
                    helper.register()
                    I18N[lang_code] = helper
    except Exception as e:
        print(f"[SimpleCameraMatch] Translation register error: {e}")

def unregister():
    for helper in I18N.values():
        helper.unregister()
    I18N.clear()

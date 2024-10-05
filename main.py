import json
import time
import streamlit as st
from openai import OpenAI, RateLimitError
import docx
from xml.etree import ElementTree as ET
import re

# Словарь для соответствия названий разделов и их id
if "section_ids" not in st.session_state:
    st.session_state["section_ids"] = {}

# Функция для чтения .docx файла
def read_docx(file_path):
    doc = docx.Document(file_path)
    full_text = []
    for para in doc.paragraphs:
        full_text.append(para.text)
    return '\n'.join(full_text)

# Функция для извлечения XML из текста ответа
def extract_xml_from_response(response_text):
    """Извлекает XML из общего текста ответа GPT."""
    match = re.search(r"(<sections[\s\S]*?</sections>)", response_text)
    if match:
        return match.group(0)
    return ""

# Функция для извлечения нужного раздела из XML ответа
def extract_section_by_id(xml_response, section_id):
    try:
        root = ET.fromstring(xml_response)
        for section in root.findall('section'):
            if section.attrib['id'] == section_id:
                return section.text.strip() if section.text else ""
        return ""
    except ET.ParseError:
        return ""
    
def xml_to_markdown(xml_string):
    """Преобразует XML-строку в формат Markdown."""
    try:
        root = ET.fromstring(xml_string)
        markdown_content = []

        for section in root.findall('section'):
            section_id = section.attrib.get('id')
            section_name = section.attrib.get('name')
            section_content = section.text.strip() if section.text else ''
            
            # Форматирование заголовков и контента в Markdown
            markdown_content.append(f"## {section_name} (ID: {section_id})\n")
            markdown_content.append(section_content + "\n\n")  # Добавляем контент секции
            
            # Обрабатываем вложенные элементы, если они есть
            for sub_section in section.findall('sub_section'):
                sub_title = sub_section.find('title').text if sub_section.find('title') is not None else 'Подраздел'
                sub_content = sub_section.text.strip() if sub_section.text else ''
                
                markdown_content.append(f"### {sub_title}\n")
                markdown_content.append(sub_content + "\n\n")
                
        return ''.join(markdown_content).strip()
    except ET.ParseError:
        return "Empty text"

# Функция для замены старого раздела новым в основном документе
def replace_section_in_document(document_text, section_id, section_name, new_section_content): 
    section_marker_start = f"<section id='{section_id}' name='{section_name}'>"
    section_marker_end = "</section>"
    
    start_index = document_text.find(section_marker_start)
    end_index = document_text.find(section_marker_end, start_index) + len(section_marker_end)
    
    if start_index == -1 or end_index == -1:
        return document_text
    
    if not new_section_content:
        return document_text
    
    updated_document = document_text[:start_index] + section_marker_start + "\n" + new_section_content + "\n" + document_text[end_index:]
    print('@@updated_document', updated_document)
    return updated_document

# Функция для извлечения текста между маркерами
def extract_plaintext(input_string):
    start_marker = "Текущий текст:"
    end_marker = "---"
    
    start_index = input_string.find(start_marker)
    if start_index == -1:
        return ""
    
    start_index += len(start_marker)
    end_index = input_string.find(end_marker, start_index)
    if end_index == -1:
        return ""
    
    extracted_text = input_string[start_index:end_index].strip()
    return extracted_text

# Функция для извлечения названия раздела из пользовательского запроса
def get_section_name_from_prompt(prompt):
    # Ищем фразу типа "изменить раздел 'Введение'"
    match = re.search(r"раздел\s*['\"]?([\w\s]+)['\"]?", prompt, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None

# Функция для получения id секции по названию
def get_section_id_by_name(section_name):
    return st.session_state["section_ids"].get(section_name)

# Функция для обновления словаря section_ids новыми секциями из XML
def update_section_ids_from_xml(xml_response):
    """Обновление словаря section_ids из XML кода, если он присутствует в ответе."""
    xml_code = extract_xml_from_response(xml_response)
    print('@xml_code', xml_code)
    if not xml_code:
        st.write("XML код не найден в ответе.")
        return
    try:
        root = ET.fromstring(xml_code)
        for section in root.findall('section'):
            section_name = section.attrib.get('name')  # Предполагается, что имя секции хранится в атрибуте name
            section_id = section.attrib.get('id')      # ID секции
            if section_name and section_id:
                if section_name not in st.session_state["section_ids"]:  # Проверяем, существует ли уже раздел в словаре
                    st.session_state["section_ids"][section_name] = section_id
                    st.write(f"Новый раздел добавлен: {section_name} с id {section_id}")
                else:
                    st.write(f"Раздел '{section_name}' уже существует с id {st.session_state["section_ids"][section_name]}")
    except ET.ParseError:
        st.write("Ошибка парсинга XML")

# Подключение к OpenAI API
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

st.title("ChatGPT-like clone")

if "openai_model" not in st.session_state:
    st.session_state["openai_model"] = "gpt-4o"

if "text" not in st.session_state:
    st.session_state["document"] = "Empty text"

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Чтение системных данных
with open("dataset.txt", "r") as file:
    dataset = file.read()

# Чтение документа с техническим заданием
tech_specs = read_docx("tech-specs.docx")

# Объединение данных
combined_content = dataset + "\n" + tech_specs

# Прием пользовательского ввода
if prompt := st.chat_input("Введите запрос (например, указание начальных данных или изменение раздела):"):
    # Добавление пользовательского сообщения в историю
    st.session_state.messages.append({"role": "user", "content": prompt})

    recent_messages = st.session_state.messages[-3:]

    with st.chat_message("user"):
        st.markdown(prompt)

    # Проверяем, указан ли конкретный раздел в запросе
    section_name = get_section_name_from_prompt(prompt)

    print('@@section_name', section_name)
    
    if section_name:
        section_id = get_section_id_by_name(section_name)
        if section_id:
            st.write(f"Найден раздел '{section_name}' с id {section_id}")
        else:
            st.write(f"Раздел '{section_name}' не найден в словаре. Ждем ответа от GPT.")
            section_id = None
    else:
        section_id = None
        st.write("Запрос не содержит указания раздела. Продолжаем без раздела.")

    # Формируем сообщение для GPT
    if section_id:
        messages = [
            {"role": "system", "content": combined_content},
            {"role": "user", "content": f"Я хочу изменить раздел '{section_name}', id = {section_id}. Расскажите, какие изменения возможны."},
            {"role": "user", "content": st.session_state["document"]},
            *[
                {"role": message["role"], "content": message["content"]} for message in st.session_state.messages
            ]
        ]
    else:
        messages = [
            {"role": "system", "content": combined_content},
            {"role": "user", "content": prompt},
            {"role": "user", "content": st.session_state["document"]},
            *[
                {"role": message["role"], "content": message["content"]} for message in st.session_state.messages
            ]
        ]

    # Сохранение сообщений в json файл с меткой времени
    with open(f"logs/messages_{int(time.time())}.json", "w") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)
       
    # Отправка запроса к GPT API
    with st.chat_message("assistant"):
        try:
            stream = client.chat.completions.create(
                model=st.session_state["openai_model"],
                temperature=0.7,
                messages=messages,
                stream=True,
            )
            response = st.write_stream(stream)

            print('@', response)
            
            # Обновление словаря новыми разделами из XML-ответа
            update_section_ids_from_xml(response)

            print('@@section_ids', st.session_state["section_ids"])
            
            # Если запрос содержал указание раздела, извлекаем и обновляем текст
            if section_id:
                xml_code = extract_xml_from_response(response)
                new_section_content = extract_section_by_id(xml_code, section_id)

                if xml_code:
                    if new_section_content:
                        updated_document = replace_section_in_document(st.session_state["document"], section_id, section_name, new_section_content)
                        st.session_state["document"] = updated_document


                print('@@new_section_content', new_section_content)
                
                # Если новый раздел пришел в ответе, обновляем основной документ
            else: 
                # Если запрос не содержал указание раздела, обновляем основной документ
                xml_code = extract_xml_from_response(response)
                if xml_code:
                    st.session_state["document"] = xml_to_markdown(xml_code)

        except RateLimitError as e:
            st.write("RateLimitError. Error code: 429" + "\n You assigned rate limit " + str(e.rate_limit) + "\n" + str(e))

    st.session_state.messages.append({"role": "assistant", "content": response}) 
    
    # Отображаем обновленный текст документа в боковой панели
    with st.sidebar:
        st.header("Текст документа")
        st.markdown(st.session_state["document"])
        text = st.text_area(
            label="Текущий текст",
            key="document",
            height=550,
            label_visibility='hidden'
        )

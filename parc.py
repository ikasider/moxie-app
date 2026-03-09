import os

# Настройки
project_path = r'C:\Users\ilush\OneDrive\Documents\IT Projects\moxie-app'
output_file = 'all_code.txt'
extensions = ('.py', '.html')
ignore_dirs = {'.git', 'venv', '__pycache__', '.idea', '.vscode'}

with open(output_file, 'w', encoding='utf-8') as outfile:
    for root, dirs, files in os.walk(project_path):
        # Удаляем ненужные папки из списка обхода
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        
        for file in files:
            if file.endswith(extensions):
                file_path = os.path.join(root, file)
                
                # Добавляем заголовок, чтобы понимать, откуда этот код
                outfile.write(f"\n{'='*50}\n")
                outfile.write(f"FILE: {file_path}\n")
                outfile.write(f"{'='*50}\n\n")
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as infile:
                        outfile.write(infile.read())
                except Exception as e:
                    outfile.write(f"[Ошибка при чтении файла: {e}]\n")
                
                outfile.write("\n\n")

print(f"Готово! Весь код собран в файл: {output_file}")
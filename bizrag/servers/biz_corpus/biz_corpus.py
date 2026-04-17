import pandas as pd
import json
from pathlib import Path
from ultrarag.server import UltraRAG_MCP_Server

# Initialize the MCP Server
app = UltraRAG_MCP_Server("biz_corpus")

@app.tool(output="parse_file_path,text_corpus_save_path,sheet_mode,include_header->None")
async def build_excel_corpus(
    parse_file_path: str,
    text_corpus_save_path: str,
    sheet_mode: str = "row",
    include_header: bool = True
) -> None:
    """Read an excel file or directory and convert each row into a corpus item."""
    input_path = Path(parse_file_path)
    output_path = Path(text_corpus_save_path)
    
    files_to_process = []
    if input_path.is_file():
        files_to_process.append(input_path)
    elif input_path.is_dir():
        files_to_process.extend(input_path.rglob("*.xlsx"))
        files_to_process.extend(input_path.rglob("*.xls"))
    else:
        raise FileNotFoundError(f"Input path {parse_file_path} not found")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        for file in files_to_process:
            try:
                # read all sheets
                excel_data = pd.read_excel(file, sheet_name=None, dtype=str)
                for sheet_name, df in excel_data.items():
                    df = df.fillna("")
                    columns = df.columns.tolist()
                    for idx, row in df.iterrows():
                        content_parts = []
                        for col in columns:
                            val = str(row[col]).strip()
                            if not val:
                                continue
                            if include_header:
                                content_parts.append(f"{col}={val}")
                            else:
                                content_parts.append(val)
                        
                        if not content_parts:
                            continue
                            
                        contents = "；".join(content_parts)
                        doc_id = f"{file.stem}#{sheet_name}#{idx}"
                        title = f"{file.stem} / {sheet_name}"
                        
                        doc = {
                            "id": doc_id,
                            "title": title,
                            "contents": contents,
                            "source_type": "excel",
                            "file_name": file.name,
                            "source_uri": str(file.resolve()),
                            "sheet_name": sheet_name,
                            "row_index": idx
                        }
                        f.write(json.dumps(doc, ensure_ascii=False) + "\n")
            except Exception as e:
                app.logger.warning(f"Error processing {file}: {e}")

if __name__ == "__main__":
    app.run()

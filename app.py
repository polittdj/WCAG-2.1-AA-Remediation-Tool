import gradio as gr

def process(files):
    if not files:
        return "No files uploaded."
    return f"Received {len(files)} file(s). Tool is working!"

with gr.Blocks() as demo:
    gr.Markdown("# WCAG 2.1 AA PDF Remediation Tool")
    upload = gr.File(label="Upload PDF files", file_count="multiple", file_types=[".pdf"])
    btn = gr.Button("Process Files", variant="primary")
    output = gr.Textbox(label="Result", lines=5)
    btn.click(fn=process, inputs=upload, outputs=output)

demo.launch()

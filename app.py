import gradio as gr

def process(files):
    if not files:
        return "No files uploaded."
    names = [f.name if hasattr(f, 'name') else str(f) for f in files]
    return f"Received {len(files)} file(s): {', '.join(names)}. Tool is working!"

demo = gr.Blocks()

with demo:
    gr.Markdown("# WCAG 2.1 AA PDF Remediation Tool")
    gr.Markdown("Upload PDF files to check and remediate for WCAG 2.1 AA compliance.")
    upload = gr.File(label="Upload PDF files", file_count="multiple", file_types=[".pdf"])
    btn = gr.Button("Process Files", variant="primary")
    output = gr.Textbox(label="Result", lines=5)
    btn.click(fn=process, inputs=upload, outputs=output)

demo.launch()

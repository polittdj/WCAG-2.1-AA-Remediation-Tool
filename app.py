import gradio as gr

def process(files):
    if not files:
        return "No files uploaded."
    return f"Received {len(files)} file(s). Tool is working!"

demo = gr.Interface(
    fn=process,
    inputs=gr.File(label="Upload PDF files", file_count="multiple", file_types=[".pdf"]),
    outputs=gr.Textbox(label="Result"),
    title="WCAG 2.1 AA PDF Remediation Tool",
    description="Upload PDF files to check and remediate for WCAG 2.1 AA compliance.",
)

if __name__ == "__main__":
    demo.launch()

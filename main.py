import os
import streamlit as st
from langchain.callbacks.tracers.langchain import wait_for_all_tracers
from langchain.callbacks.tracers.run_collector import RunCollectorCallbackHandler
from langchain.memory import ConversationBufferMemory, StreamlitChatMessageHistory
from langchain.schema.runnable import RunnableConfig
from langsmith import Client
from streamlit_feedback import streamlit_feedback
import json

from rag_chain import initialize_chain
from chain_openai import get_llm_chain

feedback_file_path = "feedback.txt"
feedback_records = []
prompt = ""
full_response = ""
user_name = ""

st.set_page_config(
    page_title="Chat with the Streamlit Docs"
)

# Set LangSmith environment variables
os.environ["OPENAI_API_KEY"] = st.secrets["api_keys"]["OPENAI_API_KEY"]
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"

use_secret_key = st.sidebar.toggle(label="Demo LangSmith API key", value=True)


# Conditionally set the project name based on the toggle
if use_secret_key:
    os.environ["LANGCHAIN_PROJECT"] = "Streamlit Demo"
else:
    project_name = st.sidebar.text_input(
        "Name your LangSmith Project:", value="Streamlit Demo"
    )
    os.environ["LANGCHAIN_PROJECT"] = project_name


# Conditionally get the API key based on the toggle
if use_secret_key:
    langchain_api_key = st.secrets["api_keys"][
        "LANGSMITH_API_KEY"
    ]  # assuming it's stored under this key in secrets
else:
    langchain_api_key = st.sidebar.text_input(
        "👇 Add your LangSmith Key",
        value="",
        placeholder="Your_LangSmith_Key_Here",
        label_visibility="collapsed",
    )
if langchain_api_key is not None:
    os.environ["LANGCHAIN_API_KEY"] = langchain_api_key

if "last_run" not in st.session_state:
    st.session_state["last_run"] = "some_initial_value"

langchain_endpoint = "https://api.smith.langchain.com"

col1, col2, col3 = st.columns([0.6, 3, 1])

st.write("")

st.subheader("LLMOps using Retrieval Augmented Generation")


st.markdown("Chat with the Streamlit Documentations")

# Check if the LangSmith API key is provided
if not langchain_api_key or langchain_api_key.strip() == "Your_LangSmith_Key_Here":
    st.info("⚠️ Add your [LangSmith API key](https://python.langchain.com/docs/guides/langsmith/walkthrough) to continue, or switch to the Demo key")
else:
    client = Client(api_url=langchain_endpoint, api_key=langchain_api_key)

# Initialize State
if "trace_link" not in st.session_state:
    st.session_state.trace_link = None
if "run_id" not in st.session_state:
    st.session_state.run_id = None

_DEFAULT_SYSTEM_PROMPT = ""
system_prompt = _DEFAULT_SYSTEM_PROMPT = ""
system_prompt = system_prompt.strip().replace("{", "{{").replace("}", "}}")

chain_type = st.sidebar.radio(
    "Choose your LLM:",
    ("Classic `GPT 3.5` LLM", "RAG LLM"),
    index=1,
)

user_name = st.sidebar.text_input("Your Name", value="")

memory = ConversationBufferMemory(
    chat_memory=StreamlitChatMessageHistory(key="langchain_messages"),
    return_messages=True,
    memory_key="chat_history",
)

if chain_type == "Classic `GPT 3.5` LLM":
    chain = get_llm_chain(system_prompt, memory)

else:  # This will be triggered when "RAG LLM for Streamlit Docs ✨" is selected
    chain = initialize_chain(system_prompt, _memory=memory)

if st.sidebar.button("Clear message history"):
    print("Clearing message history")
    memory.clear()
    st.session_state.trace_link = None
    st.session_state.run_id = None


# NOTE: This won't be necessary for Streamlit 1.26+, you can just pass the type directly
# https://github.com/streamlit/streamlit/pull/7094
def _get_openai_type(msg):
    if msg.type == "human":
        return "user"
    if msg.type == "ai":
        return "assistant"
    if msg.type == "chat":
        return msg.role
    return msg.type

for msg in st.session_state.langchain_messages:
    streamlit_type = _get_openai_type(msg)
    avatar = "🦜" if streamlit_type == "assistant" else None
    with st.chat_message(streamlit_type, avatar=avatar):
        st.markdown(msg.content)

run_collector = RunCollectorCallbackHandler()
runnable_config = RunnableConfig(
    callbacks=[run_collector],
    tags=["Streamlit Chat"],
)
if st.session_state.trace_link:
    st.sidebar.markdown(
        f'<a href="{st.session_state.trace_link}" target="_blank"><button>Latest Trace: 🛠️</button></a>',
        unsafe_allow_html=True,
    )

def _reset_feedback():
    st.session_state.feedback_update = None
    st.session_state.feedback = None


MAX_CHAR_LIMIT = 500  # Adjust this value as needed

prompt = None
full_response = ""

if prompt := st.chat_input(placeholder="Ask a question about the Streamlit docs!"):

    if len(prompt) > MAX_CHAR_LIMIT:
        st.warning(f"⚠️ Your input is too long! Please limit your input to {MAX_CHAR_LIMIT} characters.")
        prompt = None  # Reset the prompt so it doesn't get processed further
    else:
        st.chat_message("user").write(prompt)
        _reset_feedback()
        with st.chat_message("assistant", avatar="🦜"):
            message_placeholder = st.empty()
            full_response = ""

            input_structure = {"input": prompt}

            if chain_type == "RAG LLM":
                input_structure = {
                    "question": prompt,
                    "chat_history": [
                        (msg.type, msg.content)
                        for msg in st.session_state.langchain_messages
                    ],
                }

            if chain_type == "Classic `GPT 3.5` LLM":
                message_placeholder.markdown("thinking...")
                full_response = chain.invoke(input_structure, config=runnable_config)[
                    "text"
                ]

            else:
                for chunk in chain.stream(input_structure, config=runnable_config):
                    full_response += chunk["answer"]  # Updated to use the 'answer' key
                    message_placeholder.markdown(full_response + "▌")
                memory.save_context({"input": prompt}, {"output": full_response})

            message_placeholder.markdown(full_response)

            # The run collector will store all the runs in order. We'll just take the root and then
            # reset the list for next interaction.
            run = run_collector.traced_runs[0]
            run_collector.traced_runs = []
            st.session_state.run_id = run.id
            wait_for_all_tracers()
            # Requires langsmith >= 0.0.19
            url = client.share_run(run.id)
            # Or if you just want to use this internally
            # without sharing
            # url = client.read_run(run.id).url
            st.session_state.trace_link = url

    
    feedback_option = "thumbs"

    has_chat_messages = len(st.session_state.get("langchain_messages", [])) > 0

    # Only show the feedback toggle if there are chat messages
    if has_chat_messages:
        feedback_option = (
            "faces" if st.toggle(label="`Thumbs` ⇄ `Faces`", value=False) else "thumbs"
        )
    else:
        pass


if st.session_state.get("run_id"):
    feedback = streamlit_feedback(
        feedback_type=feedback_option,
        optional_text_label="[Optional] Please provide an explanation",
        key=f"feedback_{st.session_state.run_id}",
    )

    score_mappings = {
        "thumbs": {"👍": 1, "👎": -1},
        "faces": {"😀": 1, "🙂": 0.5, "😐": 0, "🙁": -0.5, "😞": -1},
    }

    scores = score_mappings[feedback_option]

    if feedback:
        score = scores.get(feedback["score"])

        if score is not None:
            feedback_record = {
                "user_name": user_name,
                "user_prompt": system_prompt,
                "model_response": full_response,
                "score": score,
                "comment": feedback.get("text"),
            }

            # Append the feedback record to the list
            feedback_records.append(feedback_record)

            # Save the list of feedback records to a local JSON file
            with open(feedback_file_path, "a") as feedback_file:
                feedback_file.write(json.dumps(feedback_records) + "\n")

            st.session_state.feedback = {
                "score": score,
            }
        else:
            st.warning("Invalid Feedback Score.")
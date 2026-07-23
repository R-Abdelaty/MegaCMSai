from dotenv import load_dotenv
load_dotenv()
import random
from datetime import date, timedelta

from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.messages import HumanMessage
from langchain.messages import ToolMessage
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

# class WordBudget(AgentMiddleware):
#     """Stop emails whose message exceeds the configured word limit."""

#     def __init__(self, maxWords: int = 100):
#         super().__init__()
#         if maxWords < 1:
#             raise ValueError("maxWords must be at least 1")
#         self.max_words = maxWords

#     def wrap_tool_call(self, request, handler):
#         if request.tool_call["name"] == "sendMail":
#             email_message = request.tool_call["args"].get("M", "")
#             word_count = len(email_message.split())
#             if word_count > self.max_words:
#                 return ToolMessage(
#                     content=("Yo that shit was too long to send"),
#                     tool_call_id=request.tool_call["id"],
#                 )

#         return handler(request)

@tool 
def List10Mails(M:str,E:str) -> str:
    """List the first 10 emails from the university website"""
    #code here
    return 

agent = create_agent(
    model= init_chat_model("anthropic:claude-haiku-4-5"),
    system_prompt="Your job is to be a email assistant for my Guc university website, be consise dont yap to much just use the tools to get information you need and help the user. try not to change or paraphrase the info from the emails be accurate",
    tools=[List10Mails],
    checkpointer=InMemorySaver(),
)

config = {"configurable": {"thread_id": "mail-checker"}}

while True:
    x = input("- enter your message:")
    result = agent.invoke({"messages": [HumanMessage(x)]}, config)
    result["messages"][-1].pretty_print()
    print(" ")
    print("================================================================================")

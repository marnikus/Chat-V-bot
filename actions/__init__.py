# Actions package
# Importing the modules here registers every action block in the
# BaseAction registry (actions.base_action._REGISTRY). Without this the
# backend cannot build or execute any stack blocks.
from actions.base_action import BaseAction, ActionResult, get_action_class, all_action_ids
from actions.click_main_tab import ClickMainTab
from actions.click_back import ClickBack
from actions.click_user import ClickUser
from actions.click_send import ClickSend
from actions.find_element import FindElement
from actions.wait_page import WaitPageLoad
from actions.scroll_parse import ScrollParse
from actions.type_message import TypeMessage
from actions.attach_image import AttachImage
from actions.pause import Pause
from actions.conditional_skip import ConditionalSkip

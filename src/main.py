import openai
import discord
from discord import Message as DiscordMessage
import logging
from typing import Optional, List
from src.base import Message, Conversation
from src.constants import (
    BOT_INVITE_URL,
    DISCORD_BOT_TOKEN,
    ACTIVATE_THREAD_PREFX,
    MAX_THREAD_MESSAGES,
    SECONDS_DELAY_RECEIVING_MSG,
    OPENAI_API_KEY,
    HTTP_PROXY,
)
import asyncio
from src.utils import (
    logger,
    should_block,
    close_thread,
    is_last_message_stale,
    discord_message_to_message,
)
from src import chat_completion
from src.chat_completion import ChatRole, chat_completion, process_response
from src.moderation import (
    moderate_message,
    send_moderation_blocked_message,
    send_moderation_flagged_message,
)

logging.basicConfig(
    format="[%(asctime)s] [%(filename)s:%(lineno)d] %(message)s", level=logging.INFO
)

openai.api_key = OPENAI_API_KEY
openai.proxy = HTTP_PROXY

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents, proxy=HTTP_PROXY)
tree = discord.app_commands.CommandTree(client)


@client.event
async def on_ready():
    logger.info(f"We have logged in as {client.user}. Invite URL: {BOT_INVITE_URL}")
    await tree.sync()


@tree.command(name="chat_with_prompt", description="Create a new thread for conversation")
@discord.app_commands.checks.has_permissions(send_messages=True)
@discord.app_commands.checks.has_permissions(view_channel=True)
@discord.app_commands.checks.bot_has_permissions(send_messages=True)
@discord.app_commands.checks.bot_has_permissions(view_channel=True)
@discord.app_commands.checks.bot_has_permissions(manage_threads=True)
async def chat_with_prompt_command(interaction: discord.Interaction, prompt: str):
    try:
        # only support creating thread in text channel
        if not isinstance(interaction.channel, discord.TextChannel):
            return

        # block servers not in allow list
        if should_block(guild=interaction.guild):
            return

        user = interaction.user # 非机器人
        logger.info(f"Chat with prompt '{prompt}' by {user}")
        try:
            # moderate the message
            # flagged_str, blocked_str = await moderate_message(message=message, user=user)
            # await send_moderation_blocked_message(
            #     guild=int.guild,
            #     user=user,
            #     blocked_str=blocked_str,
            #     message=message,
            # )
            # if len(blocked_str) > 0:
            #     # message was blocked
            #     await int.response.send_message(
            #         f"Your prompt has been blocked by moderation.\n{message}",
            #         ephemeral=True,
            #     )
            #     return

            embed: Embed = discord.Embed(
                description=f"<@{user.id}> wants to chat! 🤖💬",
                color=discord.Color.green(),
            )
            embed.add_field(name=user.name, value=prompt)

            # if len(flagged_str) > 0:
            #     # message was flagged
            #     embed.color = discord.Color.yellow()
            #     embed.title = "⚠️ This prompt was flagged by moderation."

            await interaction.response.send_message(embed=embed)
            response = await interaction.original_response()

            # await send_moderation_flagged_message(
            #     guild=interaction.guild,
            #     user=user,
            #     flagged_str=flagged_str,
            #     message=message,
            #     url=response.jump_url,
            # )
        except Exception as e:
            logger.exception(e)
            await interaction.response.send_message(
                f"Failed to start chat {str(e)}", ephemeral=True
            )
            return

        # 由User创建thread
        thread = await response.create_thread(
            name=f"{ACTIVATE_THREAD_PREFX} {user.name[:20]} - {prompt[:30]}",
            slowmode_delay=1,
            reason="gpt-bot",
            auto_archive_duration=60,
        )
        async with thread.typing():
            # fetch completion
            response_data = await chat_completion(
                [Message(ChatRole.System.value, prompt)]
            )

            # send the result
            await process_response(
                user=user, thread=thread, response_data=response_data
            )
    except Exception as e:
        logger.exception(e)
        await interaction.response.send_message(
            f"Failed to start chat {str(e)}", ephemeral=True
        )


# calls for each message
@client.event
async def on_message(message: DiscordMessage):
    try:
        # block servers not in allow list
        if should_block(guild=message.guild):
            return

        # ignore messages from the bot
        if message.author == client.user:
            return

        # ignore messages not in a thread
        channel = message.channel
        if not isinstance(channel, discord.Thread):
            return

        # ignore threads not created by the bot
        thread = channel
        if thread.owner_id != client.user.id:
            return

        # ignore threads that are archived locked or title is not what we want
        if (
            thread.archived
            or thread.locked
            or not thread.name.startswith(ACTIVATE_THREAD_PREFX)
        ):
            # ignore this thread
            return

        if thread.message_count > MAX_THREAD_MESSAGES:
            # too many messages, no longer going to reply
            await close_thread(thread=thread)
            return

        # moderate the message
        # flagged_str, blocked_str = await moderate_message(
        #     message=message.content, user=message.author
        # )
        # await send_moderation_blocked_message(
        #     guild=message.guild,
        #     user=message.author,
        #     blocked_str=blocked_str,
        #     message=message.content,
        # )
        # if len(blocked_str) > 0:
        #     try:
        #         await message.delete()
        #         await thread.send(
        #             embed=discord.Embed(
        #                 description=f"❌ **{message.author}'s message has been deleted by moderation.**",
        #                 color=discord.Color.red(),
        #             )
        #         )
        #         return
        #     except Exception as e:
        #         await thread.send(
        #             embed=discord.Embed(
        #                 description=f"❌ **{message.author}'s message has been blocked by moderation but could not be deleted. Missing Manage Messages permission in this Channel.**",
        #                 color=discord.Color.red(),
        #             )
        #         )
        #         return
        # await send_moderation_flagged_message(
        #     guild=message.guild,
        #     user=message.author,
        #     flagged_str=flagged_str,
        #     message=message.content,
        #     url=message.jump_url,
        # )
        # if len(flagged_str) > 0:
        #     await thread.send(
        #         embed=discord.Embed(
        #             description=f"⚠️ **{message.author}'s message has been flagged by moderation.**",
        #             color=discord.Color.yellow(),
        #         )
        #     )

        # wait a bit in case user has more messages
        if SECONDS_DELAY_RECEIVING_MSG > 0:
            await asyncio.sleep(SECONDS_DELAY_RECEIVING_MSG)
            if is_last_message_stale(
                interaction_message=message,
                last_message=thread.last_message,
                bot_id=client.user.id,
            ):
                # there is another message, so ignore this one
                return

        logger.info(
            f"Thread message to process - {message.author}: {message.content[:50]} - {thread.name} {thread.jump_url}"
        )
            
        channel_messages: List[Optional[Message]] = []
        index = 0
        async for message in thread.history(limit=MAX_THREAD_MESSAGES, oldest_first=True):
            channel_messages.append(discord_message_to_message(client=client, index=index, message=message))
            index += 1
        channel_messages = [x for x in channel_messages if x is not None]

        print("===========start============")
        for m in channel_messages:
            print(m)
        print("===========end============")

        # generate the response
        async with thread.typing():
            response_data = await chat_completion(
                messages=channel_messages
            )

        if is_last_message_stale(
            interaction_message=message,
            last_message=thread.last_message,
            bot_id=client.user.id,
        ):
            # there is another message and its not from us, so ignore this response
            return

        # send response
        await process_response(
            user=message.author, thread=thread, response_data=response_data
        )
    except Exception as e:
        logger.exception(e)


client.run(DISCORD_BOT_TOKEN)

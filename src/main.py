import openai
import discord
from discord import Message as DiscordMessage
import logging
from typing import Optional, List
import src.config as config
import asyncio
import src.utils as utils

from src import chat_completion
from src.chat_completion import chat_completion, CompletionData, CompletionResult, ChatMessage

logging.basicConfig(
    format="[%(asctime)s] [%(filename)s:%(lineno)d] %(message)s", level=logging.INFO
)

openai.api_key = config.OPENAI_API_KEY
openai.proxy = config.HTTP_PROXY

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents, proxy=config.HTTP_PROXY)
tree = discord.app_commands.CommandTree(client)


def discord_message_to_chat_message(client: discord.Client, message: DiscordMessage) -> Optional[ChatMessage]:
    if (message.type == discord.MessageType.default):
        if message.content:
            role = "assistant" if message.author == client.user else "user"
            return ChatMessage(role, content=message.content)
        elif (message.embeds
              and len(message.embeds) > 0
              and len(message.embeds[0].fields) > 0):
            field = message.embeds[0].fields[0]
            if field.value:
                return ChatMessage("system", content=field.value)

    return None


async def process_response(
    thread: discord.Thread, response_data: CompletionData
):
    status = response_data.status
    reply_text = "" if response_data.reply_text == None else response_data.reply_text.content
    status_text = response_data.status_text
    if status is CompletionResult.OK:
        if reply_text == "":
            await thread.send(
                embed=discord.Embed(
                    description=f"**Invalid response** - empty response",
                    color=discord.Color.yellow(),
                )
            )
        else:
            shorter_response = utils.split_into_shorter_messages(reply_text)
            for r in shorter_response:
                await thread.send(r)
    elif status is CompletionResult.TOO_LONG:
        await utils.close_thread(thread)
    elif status is CompletionResult.INVALID_REQUEST:
        await thread.send(
            embed=discord.Embed(
                description=f"**Invalid request** - {status_text}",
                color=discord.Color.yellow(),
            )
        )
    else:
        await thread.send(
            embed=discord.Embed(
                description=f"**Error** - {status_text}",
                color=discord.Color.yellow(),
            )
        )


@client.event
async def on_ready():
    utils.logger.info(
        f"We have logged in as {client.user}. Invite URL: {config.BOT_INVITE_URL}")
    await tree.sync()


@tree.command(name="chat", description="Create a new private thread for conversation")
@discord.app_commands.checks.has_permissions(send_messages=True)
@discord.app_commands.checks.has_permissions(view_channel=True)
@discord.app_commands.checks.bot_has_permissions(send_messages=True)
@discord.app_commands.checks.bot_has_permissions(view_channel=True)
@discord.app_commands.checks.bot_has_permissions(manage_threads=True)
async def chat_command(interaction: discord.Interaction, title: str, prompt: str):
    try:
        # only support creating thread in text channel
        if not isinstance(interaction.channel, discord.TextChannel):
            return

        # block servers not in allow list
        if utils.should_block(guild=interaction.guild):
            return

        user = interaction.user
        utils.logger.info(f"Chat command by by {user}")

        # create thread
        thread = await interaction.channel.create_thread(
            name=f"{config.ACTIVATE_THREAD_PREFX} {title[:20]}",
            type=discord.ChannelType.private_thread,
            reason="GPT-Bot",
            slowmode_delay=1,
        )
        await thread.add_user(interaction.user)

        #
        embed = discord.Embed(
            description=f"<@{user.id}>",
            color=discord.Color.green(),
        )
        embed.add_field(name="Prompt:", value=prompt)
        await thread.send(embed=embed)

        #
        try:
            embed = discord.Embed(
                description=f"<@{user.id}> The private thread has created!\nid: {thread.id}",
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            utils.logger.exception(e)
            await interaction.response.send_message(
                f"Failed to create private thread {str(e)}", ephemeral=True
            )
            return

    except Exception as e:
        utils.logger.exception(e)
        await interaction.response.send_message(
            f"Failed to create private thread {str(e)}", ephemeral=True
        )


# calls for each message
@client.event
async def on_message(message: DiscordMessage):
    try:
        # block servers not in allow list
        if utils.should_block(guild=message.guild):
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
            or not thread.name.startswith(config.ACTIVATE_THREAD_PREFX)
        ):
            # ignore this thread
            return

        if thread.message_count > config.MAX_THREAD_MESSAGES:
            # too many messages, no longer going to reply
            await utils.close_thread(thread=thread)
            return

        # wait a bit in case user has more messages
        if config.SECONDS_DELAY_RECEIVING_MSG > 0:
            await asyncio.sleep(config.SECONDS_DELAY_RECEIVING_MSG)
            if utils.is_last_message_stale(
                interaction_message=message,
                last_message=thread.last_message,
                bot_id=client.user.id,
            ):
                # there is another message, so ignore this one
                return

        utils.logger.info(
            f"Thread message to process - {message.author}: {message.content[:50]} - {thread.name} {thread.jump_url}"
        )

        chat_messages: List[Optional[ChatMessage]] = []
        async for message in thread.history(limit=config.MAX_THREAD_MESSAGES, oldest_first=True):
            chat_messages.append(discord_message_to_chat_message(
                client=client, message=message))
        chat_messages = [
            message for message in chat_messages if message is not None]

        if config.DEBUG_LOG:
            utils.logger.info("===========chat messages start============")
            for chat_message in chat_messages:
                utils.logger.info(chat_message)
            utils.logger.info("===========chat messages end==============")

        # generate the response
        async with thread.typing():
            response_data = await chat_completion(
                messages=chat_messages
            )

        if utils.is_last_message_stale(
            interaction_message=message,
            last_message=thread.last_message,
            bot_id=client.user.id,
        ):
            # there is another message and its not from us, so ignore this response
            return

        # send response
        await process_response(
            thread=thread, response_data=response_data
        )
    except Exception as e:
        utils.logger.exception(e)


client.run(config.DISCORD_BOT_TOKEN)

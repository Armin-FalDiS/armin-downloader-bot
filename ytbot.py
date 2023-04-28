from yt_dlp import YoutubeDL
import logging
import os
import subprocess
import re
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

# set up logger
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# init default config
port = 22212
api_token = ''
webhook_url = ''
super_secret_password = ''
out_dir = ''
dl_url = ''

# check for config file
if not os.path.exists('bot.conf'):
    print('Bot config file is missing !')
    # create empty config file
    with open('bot.conf', 'w') as conf:
        conf.write('port=22212\napi_token=13750908:ArMiN-AFD-l30T-T0KeN\nwebhook_url=https://armin.com:88/afd/ytbot\npass=SUPER_SECRET\nout_dir=/home/Downloads/\ndl_url=https://armin.com/afd/files/')
    exit()

# parse config file
with open('bot.conf', 'r') as conf:
    # put config in dict
    config = {}
    for c in conf:
        cl = c.split('=')
        config[cl[0]] = cl[1]
    # set configs
    if 'port' in config:
        port = int(config['api_token'].strip())
    if 'api_token' in config:
        api_token = config['api_token'].strip()
    if 'webhook_url' in config:
        webhook_url = config['webhook_url'].strip()
    if 'pass' in config:
        super_secret_password = config['pass'].strip()
    if 'out_dir' in config:
        out_dir = config['out_dir'].strip()
    if 'dl_url' in config:
        dl_url = config['dl_url'].strip()

# no api token or webhook url no bot
if api_token == '' or webhook_url == '':
    print('Api token and webhook URL need to be in the bot config file')

# init whitelist
vip = []

# init container which keeps requests
requests = {}


def not_vip(id: int) -> bool:
    """Function checking whether the user is in the whitelist.

    if there is no password, returns false regardless

    Args:
        id (int): Telegram ID of the user
    """
    return id not in vip if super_secret_password != '' else False


def update_vip_list():
    """Syncs the whitelist file with the whitelist array
    """
    with open('viplist.txt', 'w') as list:
        for p in vip:
            list.write(str(p) + '\n')


def new_vip(id: int):
    """Adds a new user the whitelist and updates the file

    Args:
        id (int): Telegram ID of the user
    """
    vip.append(id)
    update_vip_list()


async def bouncer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler prompting the user for password
    """
    if update.effective_chat and update.effective_user:
        await context.bot.send_message(update.effective_chat.id, 'This is my turf G. Do you even know the super secret password ?')


async def vip_maker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler that puts the user in the whitelist
    """
    if update.effective_chat and update.effective_user:
        id = update.effective_user.id
        if not_vip(id):
            new_vip(id)
            await update.message.reply_text('YOU SHALL PASS !!')
        else:
            await update.message.reply_text('Yeah yeah yeah I heard you the first time go right ahead')


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler prompting user for URL if they are in the whitelist
    """
    if update.effective_chat and update.effective_user:
        if not_vip(update.effective_user.id):
            return
        await context.bot.send_message(update.effective_chat.id, 'Yo ! Hit me up with da URL and I will get right on it b-word !!')


async def check_vid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler returning available qualities of the inputed youtube URL
    allowing the user to choose using buttons

    Won't return qualities that have no audio
    """
    if update.effective_chat and update.effective_user:
        if not_vip(update.effective_user.id):
            return

        ans = await update.message.reply_text('Wait for it...')

        # fetch formats
        with YoutubeDL() as ydl:
            formats = []
            try:
                a = ydl.extract_info(update.message.text, download=False)
                formats = a.get('formats')
            except Exception as err:
                await ans.edit_text('That was a dumb thing to send me. Failure was ... inevitable')
                await update.effective_chat.send_message('But since you indulged little old me, here is why: ')
                await update.effective_chat.send_message(str(err))
                return
            # empty formats is wierd (since the error handler should catch it)
            if len(formats) == 0:
                await ans.edit_text('Jesus horatio ! I dunno what happened with that one !!')
                return
            # create the buttons for user
            keyboard = []
            options = []
            for f in formats:
                # skip if the file seems to contain no audio (attempt to skip non audible options)
                if 'acodec' in f and f['acodec'] == 'none':
                    continue
                # check if the file is a video
                is_video = True
                if ('height' in f and f['height'] == 'None') or ('resolution' in f and f['resolution'] == 'audio only') or ('audio_ext' in f and f['audio_ext'] != 'none'):
                    is_video = False
                # grab format identifier (used for download)
                id = f['format_id']
                # extract format (used for button label)
                format = id
                if 'format' in f:
                    format = f['format']
                elif 'format_note' in f:
                    format = f['format_note']
                # extract size if available
                size = 0
                if 'filesize' in f:
                    size = f['filesize']
                elif 'filesize_approx' in f:
                    size = f['filesize_approx']
                if size == 0:
                    size = '??'
                else:
                    try:
                        size = '{:0.2f}'.format(int(size) * 0.000001)
                    except:
                        size = '??'
                ext = f['ext']
                # keyboard button lablel
                label = '{} - .{} ({} MB)'.format(format, ext, size)
                # keep request in ram
                options.append([id, update.message.text, is_video])
                # buttons carry the id given by system for the user
                keyboard.append([InlineKeyboardButton(
                    label, callback_data=len(options) - 1)])

            # keep options for the user (each user can only have one active request)
            requests[update.effective_user.id] = options
            # prompt use to choose the quality
            await ans.edit_text('What be the Quality G ?', reply_markup=InlineKeyboardMarkup(keyboard))


async def download_vid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler in charge of saving the requested file to the disk
    and sending it to the user
    """
    if update.effective_chat and update.effective_user:
        if not_vip(update.effective_user.id):
            return
        query = update.callback_query

        await query.answer('Checking...')

        try:
            # fetch the file's info from request container of the user using the index
            [id, url, is_video] = requests.pop(update.effective_user.id)[
                int(query.data)]
        except:
            await query.edit_message_text('Unacceptable')
            return

        await query.edit_message_text('Downloading...')

        # download the file grab the filename
        filename = ''
        options = {
            'outtmpl': out_dir + '%(title)s - %(format_note)s.%(ext)s',
            'format': id,
            'nocheckcertificate': True
        }
        with YoutubeDL(options) as ytdl:
            info = ytdl.extract_info(url, download=True)
            filename = ytdl.prepare_filename(info)

        # no filename no file
        if filename == '':
            await query.edit_message_text('Error proccessing your request :(')

        # new file name replacing unwanted chars with underscore
        fn = re.sub('[\s,#,\',"]', '_', filename)

        # rename file
        os.rename(filename, fn)

        # extract duration
        output = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                'stream=duration', '-of', 'default=noprint_wrappers=1:nokey=1', fn], stdout=subprocess.PIPE)
        duration = int(float(output.stdout.decode('ascii')))

        # Telegram has a limit of 50 MB for bot upload
        if os.path.getsize(fn) > 50000000:
            # prompt user to download the file from server
            await query.edit_message_text('That file is way too big for me to fit it through your small tiny hole. Go get it yourself: \n\n' + dl_url + Path(fn).name)
        else:
            # upload file to telegram
            await query.edit_message_text(text='Uploading to telegram...')

            if is_video:
                # extract thumbnail
                thumbnail_fn = fn[:fn.rfind('.')] + '.jpg'
                subprocess.run(['ffmpeg', '-i', fn, '-ss', '1', '-vframes', '1',
                               thumbnail_fn], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                # send file as video
                await context.bot.send_video(update.effective_chat.id, open(fn, 'rb'), duration=duration, thumb=open(thumbnail_fn, 'rb'))

                # clean up thumbnail file
                os.remove(thumbnail_fn)
            else:
                # send file as audio
                await context.bot.send_audio(update.effective_chat.id, open(fn, 'rb'), duration=duration)

            # clean up message
            await query.delete_message()


if os.path.exists('viplist.txt'):
    # read the whitelist
    with open('viplist.txt', 'r') as list:
        for l in list:
            vip.append(int(l))
else:
    # create whitelist file if it doesn't exist
    update_vip_list()

app = ApplicationBuilder().token(api_token).build()
app.add_handler(CommandHandler('start', start))
app.add_handler(CommandHandler('imvip', bouncer))
# password is checked using Text filter
app.add_handler(MessageHandler(filters.Text(
    [super_secret_password]) & (~filters.COMMAND), vip_maker))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), check_vid))
app.add_handler(CallbackQueryHandler(download_vid))

# start the webhook
app.run_webhook(port=port, webhook_url=webhook_url, stop_signals=None)

# app.run_polling(stop_signals=None)

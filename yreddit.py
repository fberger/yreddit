#!/usr/bin/env python
import praw
from apiclient.discovery import build
from apiclient.http import HttpError, BatchHttpRequest
from oauth2client.file import Storage
from oauth2client.client import flow_from_clientsecrets
from oauth2client.tools import run
import httplib2
import logging

logging.basicConfig(level=logging.INFO)

CLIENT_SECRETS_FILE = "client_secrets.json"
YOUTUBE_READ_WRITE_SCOPE = "https://www.googleapis.com/auth/youtube"
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

def client():
    flow = flow_from_clientsecrets(CLIENT_SECRETS_FILE,
                                   message='Missing client secrets',
                                   scope=YOUTUBE_READ_WRITE_SCOPE)
    storage = Storage("oauth2.json")
    credentials = storage.get()

    if credentials is None or credentials.invalid:
        logging.error('Invalid credentials')
        credentials = run(flow, storage)

    return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION,
                  http=credentials.authorize(httplib2.Http()))

def get_youtube_urls(videos):
    for v in videos:
        if not v.media:
            logging.info('Skipping non media video submission %s', v)
            continue
        oembed = v.media.get('oembed', {})
        if 'provider_url' not in oembed or oembed['provider_url'] != 'https://www.youtube.com/':
            logging.info('Skipping non-youtube video submission: %s', oembed)
            continue
        yield oembed['url']

def get_videos_by_topness():
    reddit = praw.Reddit(user_agent='yreddit')
    videos = reddit.get_subreddit('videos')
    seen = set()
    for generator in (videos.get_top_from_day(), videos.get_top_from_hour(), videos.get_hot()):
        for url in get_youtube_urls(generator):
            if url not in seen:
                seen.add(url)
                yield url

def get_playlist(youtube, title):
    for playlist in youtube.playlists().list(mine=True, part='snippet').execute()['items']:
        if playlist['snippet']['title'] == title:
            return playlist
    return None

def get_fresh_playlist(youtube, title):
    playlist = get_playlist(youtube, title)
    if not playlist:
        return youtube.playlists().insert(body={'snippet': {'title': title}, 'status': {'privacyStatus': 'public'}}, part='snippet,status').execute()
    items = youtube.playlistItems().list(playlistId=playlist['id'], part='id', maxResults=50).execute()['items']
    for item in items:
        youtube.playlistItems().delete(id=item['id']).execute()
    return playlist

def add_video_url(youtube, playlist, video_id):
    try:
        youtube.playlistItems().insert(part='snippet', body={'snippet': {
            'playlistId': playlist['id'],
            'resourceId': {
                'kind': 'youtube#video',
                'videoId': video_id
                }}}).execute()
    except HttpError as e:
        logging.exception('Could not add video %s\nHttpError content: %s', video_id, e.content)

def to_id(url):
    _, id = url.split('=')
    return id

def watched_videos(youtube):
    history_playlist_id = youtube.channels().list(mine=True, part='contentDetails').execute()['items'][0]['contentDetails']['relatedPlaylists']['watchHistory']
    for video in youtube.playlistItems().list(playlistId=history_playlist_id, part='contentDetails', maxResults=50).execute()['items']:
        yield video['contentDetails']['videoId']

def main():
    try:
        youtube = client()
        watched_videos_ids = set(watched_videos(youtube))
        playlist = get_fresh_playlist(youtube, "Today's top reddit videos")
        for url in get_videos_by_topness():
            video_id = to_id(url)
            if video_id not in watched_videos_ids:
                add_video_url(youtube, playlist, video_id)
    except:
        logging.exception('Unexpected error')
        
if __name__ == '__main__':
    main()

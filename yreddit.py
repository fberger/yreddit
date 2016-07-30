#!/usr/bin/env python
import praw
from apiclient.discovery import build
from apiclient.http import HttpError, BatchHttpRequest
from oauth2client.file import Storage
from oauth2client.client import flow_from_clientsecrets
from oauth2client.tools import run
import httplib2
import logging
import re

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

def to_id(url):
    _, id = url.split('=')
    return id

def extract_video_id_from_html(html):
    match = re.search('src="[^"]+embed/([^?]+)', html)
    if not match:
        logging.info('embedded html does not contain simple youtube embed url: %s', html)
        return None
    return match.group(1)

def get_youtube_video_ids(videos):
    for v in videos:
        if not v.media:
            logging.info('Skipping non media video submission %s', v)
            continue
        oembed = v.media.get('oembed', {})
        if 'provider_url' not in oembed or oembed['provider_url'] != 'https://www.youtube.com/':
            logging.info('Skipping non-youtube video submission: %s', oembed)
            continue
        if 'url' in oembed:
            yield to_id(oembed['url'])
        if 'html' in oembed:
            video_id = extract_video_id_from_html(oembed['html'])
            if video_id:
                yield video_id
        else:
            logging.info('no video id extracted from oembed: %s', oembed)

def get_videos_by_topness():
    reddit = praw.Reddit(user_agent='yreddit')
    videos = reddit.get_subreddit('videos')
    seen = set()
    for generator in (videos.get_top_from_day(), videos.get_top_from_hour(), videos.get_hot()):
        for id in get_youtube_video_ids(generator):
            if id not in seen:
                seen.add(id)
                yield id

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

def watched_videos(youtube, fetch_count=50):
    history_playlist_id = youtube.channels().list(mine=True, part='contentDetails').execute()['items'][0]['contentDetails']['relatedPlaylists']['watchHistory']
    next_page_token = None
    while fetch_count > 0:
        page = youtube.playlistItems().list(playlistId=history_playlist_id,
                                            part='contentDetails',
                                            maxResults=min(50, fetch_count),
                                            pageToken=next_page_token).execute()
        fetch_count -= len(page['items'])
        for video in page['items']:
            yield video['contentDetails']['videoId']
        if 'nextPageToken' not in page:
            break
        next_page_token = page['nextPageToken']


def main():
    try:
        youtube = client()
        watched_videos_ids = set(watched_videos(youtube))
        playlist = get_fresh_playlist(youtube, "Today's top reddit videos")
        for video_id in get_videos_by_topness():
            if video_id not in watched_videos_ids:
                add_video_url(youtube, playlist, video_id)
    except:
        logging.exception('Unexpected error')
        
if __name__ == '__main__':
    main()

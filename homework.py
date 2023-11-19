import logging
import os
import sys
import time
from http import HTTPStatus

import requests
from requests.exceptions import RequestException
import telegram
from dotenv import load_dotenv

from exceptions import (EmptyResponseFromAPI, NotForSend, TelegramError,
                        WrongResponseCode)

load_dotenv()
PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TOKEN')
TELEGRAM_CHAT_ID = os.getenv('CHAT_ID')


RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}


HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


def send_message(bot: telegram.bot.Bot, message: str) -> None:
    """Отправляет сообщение в telegram."""
    try:
        logging.info('Начало отправки статуса в telegram')
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        logging.debug('Сообщение успешно отправлено в telegram')
    except telegram.error.TelegramError as error:
        logging.error(f'Ошибка отправки статуса в telegram: {error}')
    else:
        logging.info('Статус отправлен в telegram')


def get_api_answer(current_timestamp: int) -> dict:
    """Отправляем запрос к API и получаем список домашних работ.
    Также проверяем, что эндпоинт отдает статус 200.
    """
    timestamp = current_timestamp or int(time.time())
    params_request = {
        'url': ENDPOINT,
        'headers': HEADERS,
        'params': {'from_date': timestamp},
    }
    message = ('Начало запроса к API. Запрос: {url}, {headers}, {params}.'
               ).format(**params_request)
    logging.info(message)
    try:
        response = requests.get(**params_request)
        if response.status_code != HTTPStatus.OK:
            raise WrongResponseCode(
                f'Ответ API не возвращает 200. '
                f'Код ответа: {response.status_code}. '
                f'Причина: {response.reason}. '
                f'Текст: {response.text}.'
            )
        return response.json()
    except RequestException as request_error:
        message = ('API не возвращает 200. Запрос: {url}, {headers}, {params}.'
                   ).format(**params_request)
        raise WrongResponseCode(message, request_error)


def check_response(response: dict) -> list:
    """Проверяет ответ API на корректность."""
    logging.info('Проверка ответа API на корректность')
    if not isinstance(response, dict):
        raise TypeError(
            f'Ожидался ответ API в формате dict, получен {type(response)}'
        )
    if 'homeworks' not in response or 'current_date' not in response:
        raise EmptyResponseFromAPI('Нет ключа homeworks в ответе API')
    homeworks = response.get('homeworks')
    if not isinstance(homeworks, list):
        raise TypeError(
            'Ожидался список (list) в ключе "homeworks",'
            f' получен {type(homeworks)}'
        )
    return homeworks


def parse_status(homework: dict) -> str:
    """Извлекает из информации о конкретной домашней работе."""
    logging.info('Проводим проверки и извлекаем статус работы')
    if 'homework_name' not in homework:
        raise KeyError('Нет ключа homework_name в ответе API')
    homework_name = homework.get('homework_name')
    homework_status = homework.get('status')
    if homework_status not in HOMEWORK_VERDICTS:
        raise ValueError(f'Неизвестный статус работы - {homework_status}')
    return ('Изменился статус проверки работы "{homework_name}". {verdict}'
            ).format(homework_name=homework_name,
                     verdict=HOMEWORK_VERDICTS[homework_status]
                     )


def check_tokens() -> bool:
    """Проверяем, что есть все токены.
    Если нет хотя бы одного, то останавливаем бота.
    """
    logging.info('Проверка наличия всех токенов')
    if not all([PRACTICUM_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
        raise ValueError('Отсутствует один из токенов')
    return True


def main():
    """Основная логика работы бота."""
    try:
        if not check_tokens():
            raise ValueError('Отсутствует токен. Бот остановлен!')
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        current_timestamp = 0
        start_message = 'Бот начал работу'
        send_message(bot, start_message)
        logging.info(start_message)
        prev_msg = ''
        while True:
            try:
                response = get_api_answer(current_timestamp)
                current_timestamp = response.get(
                    'current_date', int(time.time())
                )
                homeworks = check_response(response)

                if not homeworks:
                    message = 'Нет новых статусов'
                else:
                    message = parse_status(homeworks[0])

                if message != prev_msg and message not in prev_msg:
                    send_message(bot, message)
                    prev_msg = message
                else:
                    logging.info(message)

            except (NotForSend, TelegramError) as error:
                message = f'Сбой в работе программы: {error}'
                logging.error(message, exc_info=True)

            except Exception as error:
                message = f'Сбой в работе программы: {error}'
                logging.error(message, exc_info=True)
                if message not in prev_msg:
                    try:
                        send_message(bot, message)
                    except TelegramError as telegram_error:
                        logging.error(
                            'Ошибка при отправке сообщения в Telegram: '
                            f'{telegram_error}'
                        )
                prev_msg = message
            finally:
                time.sleep(RETRY_PERIOD)
    except Exception as main_error:
        logging.critical(f'Произошла критическая ошибка: {main_error}')


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        handlers=[
            logging.FileHandler(
                os.path.abspath('main.log'), mode='a', encoding='UTF-8'),
            logging.StreamHandler(stream=sys.stdout)],
        format='%(asctime)s, %(levelname)s, %(funcName)s, '
               '%(lineno)s, %(name)s, %(message)s'
    )
    main()

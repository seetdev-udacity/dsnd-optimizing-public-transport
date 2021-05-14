"""Defines a Tornado Server that consumes Kafka Event data for display"""
import topic_check
from models import Lines, Weather
from consumer import KafkaConsumer
import logging
import logging.config
from pathlib import Path
from configparser import ConfigParser, ExtendedInterpolation

import tornado.ioloop
import tornado.template
import tornado.web

config = ConfigParser(interpolation=ExtendedInterpolation())
config.read(f"{Path(__file__).parents[0].parents[0]}/kafka.ini")

# Import logging before models to ensure configuration is picked up
logging.config.fileConfig(f"{Path(__file__).parents[0]}/logging.ini")


logger = logging.getLogger(__name__)


class MainHandler(tornado.web.RequestHandler):
    """Defines a web request handler class"""

    template_dir = tornado.template.Loader(
        f"{Path(__file__).parents[0]}/templates")
    template = template_dir.load("status.html")

    def initialize(self, weather, lines):
        """Initializes the handler with required configuration"""
        self.weather = weather
        self.lines = lines

    def get(self):
        """Responds to get requests"""
        logging.debug("rendering and writing handler template")
        self.write(
            MainHandler.template.generate(
                weather=self.weather, lines=self.lines)
        )


def run_server():
    """Runs the Tornado Server and begins Kafka consumption"""
    if topic_check.topic_exists(config['topics.consumers']['turnstile.summary']) is False:
        logger.fatal(
            "Ensure that the KSQL Command has run successfully before running the web server!"
        )
        exit(1)

    if topic_check.topic_exists(config['topics.consumers']['faust.station.transformed']) is False:
        logger.fatal(
            "Ensure that Faust Streaming is running successfully before running the web server!"
        )
        exit(1)

    weather_model = Weather()
    lines = Lines()
    application = tornado.web.Application(
        [(r"/", MainHandler, {"weather": weather_model, "lines": lines})]
    )
    application.listen(8888)
    # Build kafka consumers
    consumers = [
        KafkaConsumer(
            config['topics.producers']['weather'],
            weather_model.process_message,
            offset_earliest=True,
        ),
        KafkaConsumer(
            config['topics.consumers']['faust.station.transformed'],
            lines.process_message,
            offset_earliest=True,
            is_avro=False,
        ),
        KafkaConsumer(
            f"^{config['topics.producers']['station.arrival.prefix']}.*",
            lines.process_message,
            offset_earliest=True,
        ),
        KafkaConsumer(
            config['topics.consumers']['turnstile.summary'],
            lines.process_message,
            offset_earliest=True,
            is_avro=False,
        ),
    ]

    try:
        logger.info(
            "Open a web browser to http://localhost:8888 to see the Transit Status Page"
        )
        for consumer in consumers:
            tornado.ioloop.IOLoop.current().spawn_callback(consumer.consume)

        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt as e:
        logger.info("shutting down server")
        tornado.ioloop.IOLoop.current().stop()
        for consumer in consumers:
            consumer.close()


if __name__ == "__main__":
    run_server()

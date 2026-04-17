from bizrag.entrypoints.rustfs_mq_bridge import (
    enqueue_message,
    main,
    parse_args,
    run_bridge,
    run_kafka_bridge,
    run_rabbitmq_bridge,
)

__all__ = [
    "enqueue_message",
    "main",
    "parse_args",
    "run_bridge",
    "run_kafka_bridge",
    "run_rabbitmq_bridge",
]


if __name__ == "__main__":
    main()

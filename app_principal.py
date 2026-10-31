from process_handle import process_handle


def main():
    """
    Ponto de entrada do processamento principal
    do projeto Observability AI.
    """

    processo = process_handle()
    processo.executar()


if __name__ == "__main__":
    main()
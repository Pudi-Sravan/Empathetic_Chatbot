from memory.short_term import (
    initialize_short_term,
    read_short_term,
    write_short_term,
    clear_short_term
)


print("Initializing STM...")
initialize_short_term()

print("\nInitial STM:")
print(read_short_term())


print("\nWriting test STM...")

write_short_term(
    "• The caretaker mentioned that the patient becomes anxious during sudden changes.",
    [
        {
            "role": "user",
            "content": "Sudden changes make him anxious."
        },
        {
            "role": "assistant",
            "content": "A predictable routine may help reduce anxiety."
        }
    ]
)


print("\nSTM after writing:")
print(read_short_term())


print("\nClearing STM...")

clear_short_term()

print("\nSTM after clearing:")
print(read_short_term())

#################################################
1.

My brother's name is Arjun and he is 15 years old.

2.

He gets very anxious when there are sudden loud noises, especially during thunderstorms.

3.

He also becomes overwhelmed when our daily routine changes unexpectedly.

4.

What can I do when he gets anxious during a thunderstorm?

5.

Giving him his headphones and moving to a quiet room usually helps him calm down.

6.

He also likes watching nature documentaries when he is relaxed.

7.

Tomorrow we need to visit a new doctor, and I am worried because he doesn't handle unfamiliar places very well.

8.

Giving him a 10-minute warning before leaving usually makes the transition easier.

9.

Can you suggest a simple plan for tomorrow's doctor visit?

10.

Based on everything I've told you, what should I keep in mind when helping Arjun tomorrow?